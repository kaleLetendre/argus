#!/usr/bin/env bash
# One-shot setup: create .env (with a generated password) if missing, start the
# Neo4j container, wait for health, and seed the graph from the YAML workspaces.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  PW="$(openssl rand -hex 16)"
  printf 'NEO4J_URI=bolt://localhost:7687\nNEO4J_USER=neo4j\nNEO4J_PASSWORD=%s\n' "$PW" > .env
  chmod 600 .env
  echo "Created .env with a generated password."
fi

mkdir -p data/neo4j/data data/neo4j/logs
echo "Starting Neo4j..."
docker compose up -d

echo -n "Waiting for Neo4j to be healthy"
for _ in $(seq 1 30); do
  status="$(docker inspect --format '{{.State.Health.Status}}' argus-neo4j 2>/dev/null || echo starting)"
  [ "$status" = "healthy" ] && break
  echo -n "."; sleep 2
done
echo " ${status:-unknown}"

if [ -d .venv ]; then . .venv/bin/activate; fi
echo "Seeding the graph from workspaces/ ..."
python -m argus.store.importer --reset

echo "Done. Browser: http://localhost:7474  (user: neo4j, password in .env)"
