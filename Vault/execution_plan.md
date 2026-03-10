# 🤖 Personal AI Employee — Execution Plan

> **Project:** Personal AI Employee Hackathon 0  
> **Goal:** Build an Autonomous Digital FTE (Full-Time Equivalent)  
> **Tagline:** *Your life and business on autopilot. Local-first, agent-driven, human-in-the-loop.*

---

## 📋 Overview

This execution plan walks through all 4 tiers of building your Personal AI Employee, from the minimum viable setup to a fully cloud-deployed autonomous system. Complete each tier before moving to the next.

---

## 🥉 TIER 1 — Bronze: Foundation (Minimum Viable Deliverable)
**Estimated Time:** 8–12 hours  
**Goal:** Get Claude Code reading and writing to an Obsidian vault with one working Watcher.

### Tasks

- [ ] **1.1** Install all required software:
  - Claude Code (Pro subscription or Free Gemini API via Claude Code Router)
  - Obsidian v1.10.6+
  - Python 3.13+
  - Node.js v24+ LTS
  - GitHub Desktop (latest stable)

- [ ] **1.2** Create a new Obsidian vault named `AI_Employee_Vault`

- [ ] **1.3** Set up the base folder structure inside the vault:
  ```
  AI_Employee_Vault/
  ├── Needs_Action/
  ├── Plans/
  ├── Done/
  ├── Logs/
  ├── Dashboard.md
  └── Company_Handbook.md
  ```

- [ ] **1.4** Write your `Company_Handbook.md` with basic rules:
  - Preferred tone for communications
  - Payment approval thresholds
  - Priority contact list

- [ ] **1.5** Write your `Dashboard.md` template with sections for:
  - Bank balance
  - Pending messages
  - Active projects

- [ ] **1.6** Set up a UV Python project in your working directory

- [ ] **1.7** Implement ONE working Watcher script (choose one):
  - **Gmail Watcher** — monitors Gmail for important/unread emails
  - **File System Watcher** — monitors a drop folder for new files

- [ ] **1.8** Verify Claude Code can read from and write to the vault:
  ```bash
  claude --version
  # Point Claude at your vault directory
  cd ~/AI_Employee_Vault && claude
  ```

- [ ] **1.9** Wrap all AI functionality as **Agent Skills**
  - Reference: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview

- [ ] **1.10** Run a basic end-to-end test:
  - Drop a test file → Watcher detects it → Claude reads it → Claude writes a response to `/Plans`

---

> ## ✅ TIER 1 COMPLETE — BRONZE ACHIEVED!
>
> 🎉 **Congratulations! You've built the foundation of your Personal AI Employee!**
>
> **What you've accomplished:**
> - ✅ Local Obsidian vault is live as your AI's brain and dashboard
> - ✅ Claude Code is connected and reading/writing to your vault
> - ✅ At least one Watcher is running and detecting real-world events
> - ✅ Base folder workflow (`Needs_Action → Plans → Done`) is operational
> - ✅ First Agent Skills are packaged and reusable
>
> **You now have a working AI Employee that can perceive and respond to its environment.**  
> 🚀 *Ready to level up? Proceed to Tier 2 — Silver.*

---

## 🥈 TIER 2 — Silver: Functional Assistant
**Estimated Time:** 20–30 hours  
**Goal:** Add multi-source monitoring, reasoning loops, one MCP server, and human-approval workflows.

### Tasks

- [ ] **2.1** Complete all Bronze (Tier 1) requirements

- [ ] **2.2** Implement 2+ Watcher scripts:
  - Gmail Watcher (`gmail_watcher.py`)
  - WhatsApp Watcher via Playwright (`whatsapp_watcher.py`)
  - LinkedIn Watcher (optional bonus)

- [ ] **2.3** Set up automatic LinkedIn posting for business leads:
  - Schedule regular posts via MCP or automation script
  - Log post activity in `/Logs/`

- [ ] **2.4** Implement Claude reasoning loop that generates `Plan.md` files:
  ```
  Read /Needs_Action → Reason → Write /Plans/PLAN_<task>.md → Await Approval
  ```

- [ ] **2.5** Set up ONE working MCP server for external action:
  - Recommended: Email MCP for sending/drafting Gmail replies
  - Configure in `~/.config/claude-code/mcp.json`

- [ ] **2.6** Implement Human-in-the-Loop (HITL) approval workflow:
  ```
  AI writes → /Pending_Approval/<task>.md
  You move  → /Approved/
  AI acts   → MCP executes action
  ```

- [ ] **2.7** Set up basic scheduling via `cron` (Mac/Linux) or Task Scheduler (Windows):
  - Daily 8 AM briefing trigger
  - Hourly Watcher health checks

- [ ] **2.8** Package all AI logic as Agent Skills

- [ ] **2.9** Test full flow: WhatsApp keyword → Watcher → Plan → Approval → Email reply

---

> ## ✅ TIER 2 COMPLETE — SILVER ACHIEVED!
>
> 🎉 **Outstanding! Your AI Employee is now a Functional Assistant!**
>
> **What you've accomplished:**
> - ✅ Multi-source monitoring (Gmail + WhatsApp) running simultaneously
> - ✅ Claude is generating structured Plan.md files autonomously
> - ✅ One live MCP server handling real external actions
> - ✅ Human-in-the-loop safeguards protecting sensitive actions
> - ✅ Scheduled tasks running automatically without your intervention
>
> 🚀 *Ready for the next challenge? Proceed to Tier 3 — Gold.*

---

## 🥇 TIER 3 — Gold: Autonomous Employee
**Estimated Time:** 40+ hours  
**Goal:** Full cross-domain integration, multiple MCP servers, autonomous looping, accounting audit, and CEO briefing.

### Tasks

- [ ] **3.1** Complete all Silver (Tier 2) requirements

- [ ] **3.2** Achieve full cross-domain integration:
  - Personal domain: Gmail, WhatsApp, Bank
  - Business domain: Social media, payments, project tasks

- [ ] **3.3** Install and self-host **Odoo Community** for accounting:
  - Create accounting system locally (Odoo 19+)
  - Integrate via MCP server using Odoo's JSON-RPC API
  - Reference MCP: https://github.com/AlanOgic/mcp-odoo-adv

- [ ] **3.4** Integrate Facebook & Instagram:
  - Auto-post scheduled content
  - Generate weekly engagement summary

- [ ] **3.5** Integrate Twitter/X:
  - Auto-post content
  - Generate follower/engagement summary

- [ ] **3.6** Set up multiple MCP servers:
  - Email MCP
  - Browser MCP (Playwright for payment portals)
  - Calendar MCP
  - Odoo MCP

- [ ] **3.7** Implement the **Ralph Wiggum Loop** for autonomous multi-step tasks:
  ```bash
  /ralph-loop "Process all files in /Needs_Action, move to /Done when complete" \
    --completion-promise "TASK_COMPLETE" \
    --max-iterations 10
  ```
  - Reference: https://github.com/anthropics/claude-code/tree/main/.claude/plugins/ralph-wiggum

- [ ] **3.8** Build the **Weekly Business Audit & CEO Briefing**:
  - Trigger: Every Sunday night via cron
  - Input: `Business_Goals.md`, `/Tasks/Done`, `Bank_Transactions.md`
  - Output: `/Vault/Briefings/YYYY-MM-DD_Monday_Briefing.md`
  - Content: Revenue, bottlenecks, proactive cost suggestions

- [ ] **3.9** Implement error recovery and graceful degradation:
  - Exponential backoff for transient errors
  - Quarantine queue for corrupted files
  - Never auto-retry payment actions

- [ ] **3.10** Set up comprehensive audit logging in `/Vault/Logs/YYYY-MM-DD.json`:
  ```json
  {
    "timestamp": "...",
    "action_type": "email_send",
    "actor": "claude_code",
    "approval_status": "approved",
    "result": "success"
  }
  ```

- [ ] **3.11** Write architecture documentation and record demo video (5–10 min)

- [ ] **3.12** Package all AI logic as Agent Skills

---

> ## ✅ TIER 3 COMPLETE — GOLD ACHIEVED!
>
> 🎉 **Incredible! You've built a fully Autonomous AI Employee!**
>
> **What you've accomplished:**
> - ✅ Full personal + business cross-domain automation
> - ✅ Self-hosted Odoo accounting integrated via MCP
> - ✅ Facebook, Instagram, and Twitter/X auto-managed
> - ✅ Ralph Wiggum loop enabling true multi-step autonomy
> - ✅ Weekly CEO Briefing generated without any manual trigger
> - ✅ Robust error handling and comprehensive audit trails
>
> 🚀 *Want production-grade, always-on deployment? Proceed to Tier 4 — Platinum.*

---

## 💎 TIER 4 — Platinum: Always-On Cloud + Local Executive
**Estimated Time:** 60+ hours  
**Goal:** Deploy a production-grade, 24/7 cloud + local hybrid AI Employee with vault sync and strict security boundaries.

### Tasks

- [ ] **4.1** Complete all Gold (Tier 3) requirements

- [ ] **4.2** Provision a Cloud VM (always-on):
  - Recommended: Oracle Cloud Free VM (subject to availability)
  - Alternatives: AWS EC2, DigitalOcean Droplet
  - Requirements: Ubuntu 24.04, 8GB+ RAM, 20GB+ SSD

- [ ] **4.3** Define Work-Zone Specialization:
  | Zone | Owns |
  |------|------|
  | ☁️ Cloud | Email triage, draft replies, social post drafts/scheduling |
  | 💻 Local | Approvals, WhatsApp session, payments/banking, final send/post |

- [ ] **4.4** Set up Vault Sync (Phase 1) between Cloud and Local:
  - Use **Git** (recommended) or **Syncthing**
  - Folder structure for delegation:
    ```
    /Needs_Action/<domain>/
    /Plans/<domain>/
    /Pending_Approval/<domain>/
    /In_Progress/<agent>/
    /Updates/
    ```
  - Implement **claim-by-move rule**: first agent to move item to `/In_Progress/<agent>/` owns it

- [ ] **4.5** Enforce security boundaries:
  - Vault sync includes **only** markdown/state files
  - **Never sync**: `.env`, tokens, WhatsApp sessions, banking credentials
  - Cloud agent must **never store** WhatsApp sessions or payment tokens

- [ ] **4.6** Deploy Odoo Community on Cloud VM:
  - HTTPS with SSL certificate
  - Automated daily backups
  - Health monitoring
  - Cloud agent uses MCP for **draft-only** accounting actions
  - Local approval required before posting invoices/payments

- [ ] **4.7** Implement `Watchdog.py` and process management via PM2:
  ```bash
  npm install -g pm2
  pm2 start gmail_watcher.py --interpreter python3
  pm2 save && pm2 startup
  ```

- [ ] **4.8** (Optional) A2A Upgrade (Phase 2):
  - Replace some file handoffs with direct Agent-to-Agent messages
  - Keep vault as the canonical audit record

- [ ] **4.9** Platinum Demo Gate (minimum passing requirement):
  ```
  Email arrives while Local is offline
  → Cloud drafts reply + writes approval file
  → Local comes online, user reviews approval
  → Local executes send via Email MCP
  → Logs the action
  → Moves task to /Done
  ```

- [ ] **4.10** Conduct comprehensive security review:
  - Rotate all credentials
  - Verify no secrets in vault sync
  - Review 90-day audit logs
  - Test graceful degradation for all failure modes

---

> ## ✅ TIER 4 COMPLETE — PLATINUM ACHIEVED!
>
> 🏆 **LEGENDARY. You've built a production-grade Personal AI Employee!**
>
> **What you've accomplished:**
> - ✅ 24/7 always-on cloud agent handling async work while you sleep
> - ✅ Secure local agent owning all sensitive actions (payments, WhatsApp)
> - ✅ Vault sync with strict claim-by-move rules preventing race conditions
> - ✅ Odoo ERP running in the cloud with full audit trail
> - ✅ Zero secrets ever leaving the local machine
> - ✅ Production health monitoring, auto-restart, and graceful degradation
>
> **Your Digital FTE stats:**
> | Metric | Value |
> |--------|-------|
> | Availability | 168 hours/week (24/7) |
> | Annual Hours | ~8,760 hours |
> | Cost per Task | ~$0.25–$0.50 |
> | Consistency | 99%+ |
>
> 🌟 *You haven't just completed a hackathon — you've built the future of work.*  
> **Next Step:** Explore the Advanced Custom Cloud FTE Architecture →  
> https://docs.google.com/document/d/15GuwZwIOQy_g1XsIJjQsFNHCTQTWoXQhWGVMhiH0swc/edit

---

## 🔐 Security Checklist (All Tiers)

- [ ] All credentials stored in `.env` (never committed to Git)
- [ ] `.env` added to `.gitignore`
- [ ] `DRY_RUN=true` enabled during development
- [ ] Payment actions always require HITL approval
- [ ] Credentials rotated monthly
- [ ] 90-day audit log retained in `/Vault/Logs/`

---

## 📅 Oversight Schedule

| Frequency | Action |
|-----------|--------|
| Daily | 2-min Dashboard.md check |
| Weekly | 15-min action log review |
| Monthly | 1-hour comprehensive audit |
| Quarterly | Full security and access review |

---

*Execution Plan generated for Personal AI Employee Hackathon 0 — Panaversity*  
*Research Meetings: Every Wednesday 10:00 PM on Zoom*
