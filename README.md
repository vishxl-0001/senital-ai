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

## Database migrations (Alembic)

The schema is owned by **Alembic** (`backend/alembic/`), not by app startup.
`docker-compose up` applies migrations automatically: the backend container runs
`python scripts/db_migrate.py` before launching uvicorn. That script:

- on a **fresh** database, creates the full schema (`alembic upgrade head`);
- on a **pre-Alembic** database (created by the old `init_db()` DDL), stamps the
  baseline `0001_baseline`, then applies later revisions — preserving existing data;
- on an **up-to-date** database, is a no-op.

**Deploy step (required):** run migrations before/at deploy, from `backend/`:

```bash
alembic upgrade head        # or: python scripts/db_migrate.py
```

Run it from exactly **one** process (not every replica) to avoid concurrent DDL.
`init_db()` no longer issues DDL — it only logs.


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
