#!/bin/sh
# Sentinel AI — Postgres backup (Phase 5, item 18).
#
# Dumps the database with pg_dump, gzips it, prunes dumps older than the
# retention window, and (optionally) uploads off-box to Azure Blob Storage so a
# VM loss doesn't lose backups. Run on a schedule by the postgres-backup sidecar
# in docker-compose.prod.yml, or from cron on the host.
set -eu

: "${POSTGRES_HOST:=postgres}"
: "${POSTGRES_USER:=postgres}"
: "${POSTGRES_DB:=sentinel_ai}"
: "${BACKUP_DIR:=/backups}"
: "${BACKUP_RETENTION_DAYS:=7}"

# pg_dump reads the password from PGPASSWORD.
export PGPASSWORD="${POSTGRES_PASSWORD:-}"

mkdir -p "$BACKUP_DIR"
TS=$(date +%Y%m%d-%H%M%S)
OUT="$BACKUP_DIR/${POSTGRES_DB}-${TS}.sql.gz"

echo "[backup] dumping ${POSTGRES_DB} from ${POSTGRES_HOST} -> ${OUT}"
pg_dump -h "$POSTGRES_HOST" -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$OUT"
echo "[backup] wrote $(du -h "$OUT" | cut -f1) to ${OUT}"

# Retention: delete local dumps older than N days.
find "$BACKUP_DIR" -name "${POSTGRES_DB}-*.sql.gz" -mtime +"$BACKUP_RETENTION_DAYS" -delete
echo "[backup] pruned dumps older than ${BACKUP_RETENTION_DAYS} day(s)"

# Optional off-box copy to Azure Blob Storage (recommended for production).
if [ -n "${AZURE_STORAGE_CONNECTION_STRING:-}" ] && [ -n "${AZURE_BACKUP_CONTAINER:-}" ]; then
    if command -v az >/dev/null 2>&1; then
        az storage blob upload \
            --container-name "$AZURE_BACKUP_CONTAINER" \
            --file "$OUT" --name "$(basename "$OUT")" \
            --connection-string "$AZURE_STORAGE_CONNECTION_STRING" \
            --only-show-errors && echo "[backup] uploaded to Azure Blob container ${AZURE_BACKUP_CONTAINER}"
    else
        echo "[backup] AZURE_* set but 'az' CLI not in image; skipping Blob upload"
    fi
fi

echo "[backup] done"
