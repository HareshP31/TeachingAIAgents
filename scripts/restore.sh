#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUNDLE="${1:?usage: RESTORE_CONFIRM=teaching-ai-agents scripts/restore.sh BACKUP_BUNDLE}"

if [[ "${RESTORE_CONFIRM:-}" != "teaching-ai-agents" ]]; then
  echo "Refusing destructive restore. Set RESTORE_CONFIRM=teaching-ai-agents." >&2
  exit 2
fi

for file in postgres.dump documents.tgz guidebooks.tgz SHA256SUMS; do
  [[ -f "$BUNDLE/$file" ]] || { echo "Missing $file" >&2; exit 2; }
done

(
  cd "$BUNDLE"
  shasum -a 256 -c SHA256SUMS
)

cd "$ROOT"
docker compose stop backend frontend nanobot
docker compose up -d postgres
docker compose exec -T postgres sh -c \
  'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' \
  < "$BUNDLE/postgres.dump"

docker compose run --rm -T -u root backend sh -c \
  'find /data/documents -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +'
docker compose run --rm -T -u root backend tar -C /data -xzf - \
  < "$BUNDLE/documents.tgz"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
if [[ -d "$ROOT/data/guidebooks" ]]; then
  mv "$ROOT/data/guidebooks" "$ROOT/data/guidebooks.pre-restore-$STAMP"
fi
mkdir -p "$ROOT/data/guidebooks"
tar -C "$ROOT/data" -xzf "$BUNDLE/guidebooks.tgz"

docker compose up -d
echo "Restore complete. Previous guidebooks remain at data/guidebooks.pre-restore-$STAMP"
