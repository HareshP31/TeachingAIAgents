#!/bin/sh
set -eu
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example (fake mode)."
fi
docker compose up -d --build
python3 scripts/smoke.py
