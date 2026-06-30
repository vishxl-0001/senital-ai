# 🛡️ Sentinel AI — Autonomous SRE Platform

> Detect. Diagnose. **Fix.** — The AI SRE that doesn't just find the problem, it solves it.

## Architecture

```
Alert Source → Webhook Receiver → Dedup Engine → AI Investigator → RCA Engine
                                                                      ↓
                                                              Remediation Engine
                                                                      ↓
                                                    Policy Engine (auto / approve?)
                                                                      ↓
                                                         Executor → Rollback Monitor
```

## Project Structure

```
sentinel-ai/
├── backend/              # Python FastAPI — Core platform
│   ├── app/
│   │   ├── main.py       # FastAPI app entry
│   │   ├── config.py     # Settings & env vars
│   │   ├── api/          # REST API routes
│   │   ├── agents/       # AI investigation agents (LangGraph)
│   │   ├── engine/       # Core engines (policy, executor, rollback)
│   │   ├── integrations/ # External tool connectors
│   │   ├── models/       # Database models
│   │   └── db/           # Database connection
│   ├── requirements.txt
│   └── Dockerfile
├── dashboard/            # Next.js — Web UI
├── docker-compose.yml    # Run everything locally
└── .env.example          # Environment variables template
```

## Quick Start

```bash
# 1. Clone and setup
cp .env.example .env
# Edit .env with your API keys

# 2. Start everything
docker-compose up -d

# 3. Backend API running at http://localhost:8000
# 4. Dashboard running at http://localhost:3000
```

## Tech Stack

- **Backend:** Python 3.11 + FastAPI
- **AI:** OpenAI GPT-4o + LangGraph + LangChain
- **Database:** PostgreSQL + pgvector
- **Queue:** Redis + Celery
- **Communication:** Slack Bolt SDK
- **Infrastructure:** Kubernetes API
- **Dashboard:** Next.js + React

## Team

Built with 💪 by the Sentinel AI team.
