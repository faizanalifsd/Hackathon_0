"""
router.py – LLM Model Router

Routes tasks to the right model based on task type and content length:

  FAST TASKS        → Groq (llama-3.3-70b)
  LONG CONTEXT      → OpenRouter (google/gemini-flash-1.5)
  COMPLEX/HIGH-RISK → Claude CLI (kept in approval_watcher only)

Usage:
    from router import route_completion, classify_email, generate_plan

Token threshold for "long context": 2000 tokens (~1500 words).
"""

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger("router")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

LONG_CONTEXT_TOKEN_THRESHOLD = 2000   # switch to OpenRouter above this
APPROX_CHARS_PER_TOKEN = 4            # rough estimate

GROQ_MODEL = "llama-3.3-70b-versatile"
OPENROUTER_MODEL = "google/gemini-flash-1.5"

BASE_DIR = Path(__file__).parent


def _load_env():
    """Load .env if python-dotenv is available."""
    try:
        from dotenv import load_dotenv
        load_dotenv(BASE_DIR / ".env")
    except ImportError:
        pass


_load_env()


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // APPROX_CHARS_PER_TOKEN)


def _is_long_context(text: str) -> bool:
    return _estimate_tokens(text) > LONG_CONTEXT_TOKEN_THRESHOLD


# ---------------------------------------------------------------------------
# Groq (fast tasks)
# ---------------------------------------------------------------------------

def _call_groq(system: str, user: str) -> str | None:
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        log.warning("[Router] GROQ_API_KEY not set — skipping Groq")
        return None
    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            max_tokens=1500,
        )
        return response.choices[0].message.content.strip()
    except ImportError:
        log.warning("[Router] groq package not installed — run: uv pip install groq")
        return None
    except Exception as exc:
        log.error("[Router] Groq error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# OpenRouter (long context)
# ---------------------------------------------------------------------------

def _call_openrouter(system: str, user: str) -> str | None:
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        log.warning("[Router] OPENROUTER_API_KEY not set — skipping OpenRouter")
        return None
    try:
        import requests
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/faizanalifsd/Hackathon_0",
                "X-Title": "AI Vault Pipeline",
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.2,
                "max_tokens": 2000,
            },
            timeout=60,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        log.error("[Router] OpenRouter error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def route_completion(system: str, user: str, force_model: str = "auto") -> str | None:
    """
    Route a completion request to the right model.

    force_model: "groq" | "openrouter" | "auto" (default)
    Returns the model response string, or None on failure.
    """
    if force_model == "groq":
        model_name = f"Groq/{GROQ_MODEL}"
        result = _call_groq(system, user)
    elif force_model == "openrouter":
        model_name = f"OpenRouter/{OPENROUTER_MODEL}"
        result = _call_openrouter(system, user)
    else:
        # Auto-route based on content length
        content = user + system
        if _is_long_context(content):
            model_name = f"OpenRouter/{OPENROUTER_MODEL}"
            log.info("[Router] Long context (%d tokens) → %s", _estimate_tokens(content), model_name)
            result = _call_openrouter(system, user)
            if result is None:
                log.warning("[Router] OpenRouter failed — falling back to Groq")
                model_name = f"Groq/{GROQ_MODEL}"
                result = _call_groq(system, user)
        else:
            model_name = f"Groq/{GROQ_MODEL}"
            log.info("[Router] Short context (%d tokens) → %s", _estimate_tokens(content), model_name)
            result = _call_groq(system, user)
            if result is None:
                log.warning("[Router] Groq failed — falling back to OpenRouter")
                model_name = f"OpenRouter/{OPENROUTER_MODEL}"
                result = _call_openrouter(system, user)

    if result:
        log.info("[Router] Response from %s (%d chars)", model_name, len(result))
    return result


def classify_email(email_content: str) -> dict:
    """
    Classify an email: priority, status, summary, tags.
    Returns a dict with keys: priority, status, summary, tags.
    Falls back to defaults on failure.
    """
    system = """You are an email classifier for a personal AI assistant vault system.
Classify the email and respond in this EXACT format (no extra text):

priority: high | medium | low
status: needs_action | done
summary: <one sentence>
tags: [tag1, tag2]

Rules:
- high priority: urgent deadlines, payments, important meetings, legal, health
- needs_action: requires a reply or task
- done: newsletters, notifications, no reply needed"""

    result = route_completion(system, email_content, force_model="groq")

    # Parse response into dict
    out = {"priority": "medium", "status": "needs_action", "summary": "", "tags": []}
    if result:
        for line in result.splitlines():
            if line.startswith("priority:"):
                val = line.split(":", 1)[1].strip()
                if val in ("high", "medium", "low"):
                    out["priority"] = val
            elif line.startswith("status:"):
                val = line.split(":", 1)[1].strip()
                if val in ("needs_action", "done"):
                    out["status"] = val
            elif line.startswith("summary:"):
                out["summary"] = line.split(":", 1)[1].strip()
            elif line.startswith("tags:"):
                raw = line.split(":", 1)[1].strip().strip("[]")
                out["tags"] = [t.strip() for t in raw.split(",") if t.strip()]
    return out


def generate_plan(task_name: str, task_content: str) -> str | None:
    """
    Generate a structured PLAN_*.md for a Needs_Action item.
    Auto-routes to Groq (short) or OpenRouter (long).
    Returns plan markdown string or None.
    """
    is_whatsapp = "whatsapp" in task_name.lower() or "source: whatsapp" in task_content.lower()

    if is_whatsapp:
        system = """You are an AI Employee assistant. Generate a structured action plan for a WhatsApp message.
Output ONLY the plan markdown — no explanations, no code fences.

Use this EXACT format:

---
task: {task_name}
approval_needed: yes
priority: medium
source: whatsapp
---

# Plan: <short title>

## Summary
<1-2 sentence summary of what the sender wants>

## WhatsApp Reply
<Write the exact reply message that will be sent to the sender. Keep it short, friendly, and direct. This is what will be sent — the user can edit it before approving.>

---
## Your Decision

Read the reply above, edit it if needed, then check **one** box and save:

- [ ] ✅ Approve — send the WhatsApp reply above to the sender now
- [ ] ⏸ Pending Approval — hold for later review"""

    else:
        system = """You are an AI Employee assistant. Generate a structured action plan for the given task.
Output ONLY the plan markdown — no explanations, no code fences.

Use this EXACT format:

---
task: {task_name}
approval_needed: yes
priority: medium
---

# Plan: <short title>

## Summary
<2-3 sentence summary>

## Steps
1. <step>
2. <step>

## Actions Requiring Approval
- <action that needs human sign-off, e.g. sending email>
If none: _No approval-required actions._

## Notes
<any warnings or context>

---
## Your Decision

Review the plan above, make any changes you need, then check **one** box and save the file:

- [ ] ✅ Approve — execute this plan now (Claude will send the reply email)
- [ ] ⏸ Pending Approval — hold for later review

Set approval_needed: yes if steps involve emails, social posts, payments, or external actions.
Set approval_needed: no for purely internal/analysis tasks."""

    user = f"TASK FILE: {task_name}\n\nTASK CONTENT:\n{task_content}"
    return route_completion(system, user)
