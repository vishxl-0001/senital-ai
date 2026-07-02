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


## Production deployment

Use the separate production compose file:

```bash
# .env must set POSTGRES_PASSWORD and REDIS_PASSWORD (compose refuses to start otherwise)
docker compose -f docker-compose.prod.yml up -d --build
```

vs. dev, prod: runs the built image (no bind-mount / `--reload`), uvicorn with
multiple workers, **does not** publish Postgres/Redis to the host (internal
network only), password-protects Redis, and sets per-service `mem_limit`/`cpus`
sized for a small VM.

### Backups (Postgres)

A `postgres-backup` sidecar runs `backend/scripts/backup_postgres.sh` on a schedule
(`BACKUP_INTERVAL_SECONDS`, default daily): `pg_dump | gzip` into the
`postgres_backups` volume, pruning dumps older than `BACKUP_RETENTION_DAYS`
(default 7). Set `AZURE_STORAGE_CONNECTION_STRING` + `AZURE_BACKUP_CONTAINER` to
also push each dump **off-box** to Azure Blob Storage (recommended — a VM loss
otherwise takes the backups with it).

Restore a dump:

```bash
gzip -dc sentinel_ai-YYYYmmdd-HHMMSS.sql.gz | \
  docker exec -i sentinel-postgres psql -U postgres -d sentinel_ai
```

**Recommendation:** the sidecar covers the current containerized Postgres. For a
managed option with automated point-in-time restore, migrate to **Azure Database
for PostgreSQL – Flexible Server** (enable the `vector` extension); keep the
`pg_dump` sidecar as a secondary, portable backup.


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
