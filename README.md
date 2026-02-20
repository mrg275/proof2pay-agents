# Proof2Pay Agent System

Multi-agent operating system for Proof2Pay. Runs 9 AI agents that handle compliance research, market intelligence, fundraising prep, brand development, and co-founder knowledge capture — so the founders can focus on building the product.

## Quick Start

### 1. Prerequisites
- Python 3.11+
- Anthropic API key
- Slack workspace with Socket Mode app
- Google Cloud service account with Drive API (optional for Stage 1)

### 2. Install
```bash
cd proof2pay-agents
pip install -r requirements.txt
```

### 3. Configure
```bash
cp .env.example .env
# Edit .env with your credentials
```

### 4. Test locally (no Slack needed)
```bash
# List available agents
python cli.py --list

# Run a single agent task
python cli.py compliance "Produce a SOC 2 preparation checklist"

# Interactive conversation with an agent
python cli.py domain_intelligence --interactive

# Trigger the full daily cycle
python cli.py --daily
```

### 5. Run with Slack
```bash
python main.py
```

## Architecture

```
┌──────────────────────────────────────────────┐
│                  Slack                        │
│  #chief-of-staff  #domain-intel  #briefing   │
└──────────┬──────────────┬──────────┬─────────┘
           │              │          │
      ┌────▼────┐   ┌────▼────┐     │
      │ Chief   │   │ Domain  │     │ (posts)
      │ of Staff│◄──│  Intel  │     │
      └────┬────┘   └─────────┘     │
           │ dispatches              │
     ┌─────┼──────┬───────┬────┐    │
     ▼     ▼      ▼       ▼    ▼    │
  ┌─────┐┌────┐┌─────┐┌────┐┌────┐ │
  │Comp.││Mkt ││Fund ││Tech││Reg.│ │
  │     ││Res.││     ││ PM ││    │ │
  └─────┘└────┘└─────┘└────┘└────┘ │
     │     │      │       │    │    │
     └─────┴──────┴───────┴────┘    │
                  │                  │
           ┌──────▼──────┐          │
           │   Memory    │──────────┘
           │  (per-agent │
           │  summaries) │
           └─────────────┘
```

## Project Structure

```
proof2pay-agents/
├── main.py                  # Entry point: Slack bot + scheduler
├── cli.py                   # Local testing CLI
├── agents/                  # Agent system prompts
│   ├── chief_of_staff.py
│   ├── domain_intelligence.py
│   ├── technical_pm.py
│   ├── compliance.py
│   ├── market_research.py
│   ├── fundraising.py
│   ├── competitive_intel.py
│   ├── regulatory.py
│   └── brand_marketing.py
├── integrations/            # External service connectors
│   ├── anthropic_client.py  # API wrapper with retry + token tracking
│   ├── slack_bot.py         # Socket Mode listener + message routing
│   └── google_drive.py      # Knowledge base file management
├── orchestrator/            # Core runtime
│   ├── runner.py            # Executes agents with assembled context
│   ├── dispatcher.py        # Chief of Staff task routing + tool handling
│   ├── scheduler.py         # Daily cron-based agent cycle
│   └── memory_manager.py    # Per-agent persistent memory
├── memory/                  # Agent memory (auto-created at runtime)
├── config/
│   ├── agents.yaml          # Agent roster + schedules + model tiers
│   ├── priorities.md        # Company priorities (CoS references this)
│   └── context/
│       └── codebase_context.md  # Living codebase doc (Tech PM references)
├── .env.example
└── requirements.txt
```

## Agent Roster

| Agent | Channel | Schedule | Purpose |
|-------|---------|----------|---------|
| Chief of Staff | #chief-of-staff | Daily + interactive | Orchestration, briefings, dispatch |
| Domain Intelligence | #domain-intel | Always-on | Co-founder interface, product stress-testing |
| Technical PM | — | Event-triggered | Codebase brain, engineering specs |
| Compliance | — | Weekly | FedRAMP/SOC 2 tracking, gap analysis |
| Market Research | — | Weekly | Agency targeting, procurement research |
| Fundraising | — | Weekly | Investor pipeline, market sizing |
| Competitive Intel | — | Biweekly | Competitor monitoring |
| Regulatory | — | Weekly | 2 CFR 200, grant regulations, rule patterns |
| Brand & Marketing | — | Weekly | Brand identity, messaging, materials |

## Key Flows

**Co-founder shares a document:**
1. Message arrives in #domain-intel
2. Domain Intelligence Agent analyzes through product-readiness lens
3. Identifies gaps/edge cases, responds to co-founder
4. Chief of Staff picks up findings, routes to Technical PM
5. Technical PM produces engineering spec for Claude Code

**Founder requests a task:**
1. Message in #chief-of-staff: "Create a pitch deck"
2. Chief of Staff dispatches to relevant agents (Fundraising, Brand, Market Research)
3. Agents execute with cross-referenced context
4. Chief of Staff synthesizes and posts result

**Daily cycle (automated):**
1. Research agents run on schedule
2. Chief of Staff reads all outputs, generates briefing
3. Briefing posts to #daily-briefing
4. Chief of Staff dispatches follow-up tasks autonomously

## Cost Estimate

~$100-200/month total:
- Anthropic API: $90-190 (dominant cost, model tiering helps)
- Cloud VM: $6-7 (Digital Ocean / Railway / Render)
- Slack: $0 (free tier)
- Google Drive: $0 (free tier)
