#!/usr/bin/env bash
# Back up the Argus knowledge graph.
#
# Since Neo4j is the source of truth, this is your safety net. It exports the
# whole graph to a timestamped Cypher script under backups/ using APOC if
# available, and always also captures a raw offline dump of the data volume.
#
# Usage: scripts/backup.sh [label]
set -euo pipefail
cd "$(dirname "$0")/.."

# shellcheck disable=SC1091
[ -f .env ] && set -a && . ./.env && set +a

STAMP="$(date +%Y%m%d-%H%M%S)"
LABEL="${1:-manual}"
OUT="backups/${STAMP}-${LABEL}"
mkdir -p "$OUT"

# 1. Human-readable Cypher export via APOC (best-effort; needs APOC + config).
if docker exec argus-neo4j test -d /var/lib/neo4j/plugins 2>/dev/null; then
  docker exec argus-neo4j cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" \
    "CALL apoc.export.cypher.all(null, {stream:true}) YIELD cypherStatements RETURN cypherStatements" \
    > "$OUT/graph.cypher" 2>/dev/null \
    && echo "Wrote $OUT/graph.cypher" \
    || echo "APOC export unavailable (skipping Cypher dump)."
fi

# 2. Always: tar the data volume (offline-consistent enough for a home server).
docker run --rm \
  -v jarvis_neo4j_data:/data 2>/dev/null \
  -v "$(pwd)/$OUT":/backup alpine \
  tar czf /backup/neo4j-data.tgz -C / data 2>/dev/null \
  || tar czf "$OUT/neo4j-data.tgz" -C data/neo4j data \
  && echo "Wrote $OUT/neo4j-data.tgz"

echo "Backup complete: $OUT"
