#!/usr/bin/env bash
# Back up the Argus knowledge graph. Neo4j is the source of truth, so this is
# the safety net and it must actually capture data.
#
# Strategy: take a crash-consistent snapshot by briefly stopping Neo4j and
# archiving its store directory (the bind mount under data/neo4j/data), then
# restarting. Also attempts a no-downtime APOC Cypher export if APOC is present.
# Verifies the archive is non-empty and exits non-zero on failure.
#
# NOTE: this stops the Neo4j container for a few seconds. It does not touch
# networking or the remote-access server, but the graph is briefly unavailable.
#
# Usage: scripts/backup.sh [label]
set -euo pipefail
cd "$(dirname "$0")/.."

# Read creds from .env WITHOUT sourcing it as shell (don't execute file contents).
_envval() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2-; }
NEO4J_USER="$(_envval NEO4J_USER)"; NEO4J_USER="${NEO4J_USER:-neo4j}"
NEO4J_PASSWORD="$(_envval NEO4J_PASSWORD)"

STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="backups/${STAMP}-${1:-manual}"
DATA_DIR="data/neo4j/data"
mkdir -p "$OUT"

if [ ! -d "$DATA_DIR" ]; then
  echo "No Neo4j data dir at $DATA_DIR; nothing to back up." >&2
  exit 1
fi

# Best-effort, no-downtime Cypher export (only works if APOC is installed).
if [ -n "$NEO4J_PASSWORD" ] && \
   docker exec argus-neo4j cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" "RETURN 1" >/dev/null 2>&1; then
  if docker exec argus-neo4j cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" \
       "CALL apoc.export.cypher.all(null,{stream:true}) YIELD cypherStatements RETURN cypherStatements" \
       > "$OUT/graph.cypher" 2>/dev/null && [ -s "$OUT/graph.cypher" ]; then
    echo "Wrote $OUT/graph.cypher (APOC)"
  else
    rm -f "$OUT/graph.cypher"
    echo "APOC export unavailable; relying on the store archive below."
  fi
fi

# Crash-consistent store archive: stop, tar, restart.
was_running="$(docker inspect -f '{{.State.Running}}' argus-neo4j 2>/dev/null || echo false)"
restart() { [ "$was_running" = "true" ] && docker compose start neo4j >/dev/null 2>&1 || true; }
trap restart EXIT

echo "Stopping Neo4j for a consistent snapshot (brief downtime)..."
docker compose stop neo4j >/dev/null 2>&1 || true

ARCHIVE="$OUT/neo4j-store.tgz"
tar czf "$ARCHIVE" -C "$DATA_DIR" .

restart
trap - EXIT

# Verify the archive actually contains something.
if [ ! -s "$ARCHIVE" ] || [ "$(stat -c%s "$ARCHIVE" 2>/dev/null || echo 0)" -lt 1024 ]; then
  echo "Backup archive is empty or suspiciously small: $ARCHIVE" >&2
  exit 1
fi
echo "Backup complete: $OUT ($(du -h "$ARCHIVE" | cut -f1))"
