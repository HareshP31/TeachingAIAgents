#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET_ROOT="${1:?usage: scripts/backup.sh BACKUP_DIRECTORY}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARGET="$TARGET_ROOT/teaching-ai-agents-$STAMP"

mkdir -p "$TARGET"
cd "$ROOT"

docker compose exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$TARGET/postgres.dump"
docker compose exec -T backend tar -C /data -czf - documents > "$TARGET/documents.tgz"
tar -C "$ROOT/data" -czf "$TARGET/guidebooks.tgz" guidebooks
cp .env.example "$TARGET/env.example"

(
  cd "$TARGET"
  shasum -a 256 postgres.dump documents.tgz guidebooks.tgz env.example > SHA256SUMS
)

echo "$TARGET"
