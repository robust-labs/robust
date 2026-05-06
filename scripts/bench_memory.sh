#!/bin/bash
# bench_memory.sh — sweep JOB queries × {baseline, robust+join_order} and capture
# total_memory_allocated from each profile JSON. Output: <out>/memory.csv
#
# Usage:
#   ./scripts/bench_memory.sh                             # all JOB queries
#   ./scripts/bench_memory.sh --pattern '13.*'            # subset
#   ./scripts/bench_memory.sh --query 13a                 # single query
#   ./scripts/bench_memory.sh --out benchmark_results     # output dir

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

DUCKDB="$PROJECT_ROOT/build/release/duckdb"
EXT="$PROJECT_ROOT/build/release/extension/robust/robust.duckdb_extension"
DB="$PROJECT_ROOT/jobdata/job.duckdb"
QUERIES_DIR="$PROJECT_ROOT/jobdata/queries"

PATTERN=""
SPECIFIC_QUERY=""
OUT_DIR="$PROJECT_ROOT/benchmark_results"

while [[ $# -gt 0 ]]; do
    case $1 in
        --pattern) PATTERN="$2"; shift 2 ;;
        --query)   SPECIFIC_QUERY="$2"; shift 2 ;;
        --out)     OUT_DIR="$2"; shift 2 ;;
        -h|--help) sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

for f in "$DUCKDB" "$EXT" "$DB"; do
    [ -f "$f" ] || { echo "Missing: $f"; exit 1; }
done

mkdir -p "$OUT_DIR"
OUT_CSV="$OUT_DIR/memory.csv"
TMP_BASE=$(mktemp /tmp/mem_base_XXXXXX.json)
TMP_ROBUST=$(mktemp /tmp/mem_robust_XXXXXX.json)
trap 'rm -f "$TMP_BASE" "$TMP_ROBUST" "$TMP_DB"' EXIT

# if the db is locked, copy it to a temp file
ACTUAL_DB="$DB"
TMP_DB=""
if ! "$DUCKDB" "$DB" -unsigned -readonly -c "SELECT 1;" > /dev/null 2>&1; then
    TMP_DB=$(mktemp /tmp/job_mem_XXXXXX.duckdb)
    cp "$DB" "$TMP_DB"
    ACTUAL_DB="$TMP_DB"
    echo "(database locked, using temp copy)"
fi

# build query list
if [ -n "$SPECIFIC_QUERY" ]; then
    QUERY_FILES="$QUERIES_DIR/${SPECIFIC_QUERY}.sql"
    [ -f "$QUERY_FILES" ] || { echo "Query not found: $QUERY_FILES"; exit 1; }
elif [ -n "$PATTERN" ]; then
    QUERY_FILES=$(ls -1 "$QUERIES_DIR"/*.sql | grep -E "$PATTERN" || true)
else
    QUERY_FILES=$(ls -1 "$QUERIES_DIR"/*.sql | sort -V)
fi
[ -n "$QUERY_FILES" ] || { echo "No queries matched."; exit 1; }

echo "query,baseline_bytes,robust_bytes" > "$OUT_CSV"

extract_mem() {
    python3 -c "
import json, sys
d = json.load(open(sys.argv[1]))
print(d.get('total_memory_allocated', 0))
" "$1"
}

TOTAL=$(echo "$QUERY_FILES" | wc -w | tr -d ' ')
IDX=0
for qf in $QUERY_FILES; do
    qname=$(basename "$qf" .sql)
    IDX=$((IDX + 1))
    echo -n "[$IDX/$TOTAL] $qname ... "
    QUERY_SQL=$(cat "$qf")

    # baseline: jfp on, no extension
    "$DUCKDB" "$ACTUAL_DB" -unsigned -readonly -c "
PRAGMA enable_profiling='json';
PRAGMA profiling_output='$TMP_BASE';
$QUERY_SQL
" > /dev/null 2>/dev/null || { echo "baseline failed"; continue; }

    # robust: jfp off, extension loaded, join_order heuristic
    "$DUCKDB" "$ACTUAL_DB" -unsigned -readonly -c "
SET disabled_optimizers = 'join_filter_pushdown';
LOAD '$EXT';
SET robust_heuristic = 'join_order';
PRAGMA enable_profiling='json';
PRAGMA profiling_output='$TMP_ROBUST';
$QUERY_SQL
" > /dev/null 2>/dev/null || { echo "robust failed"; continue; }

    BMEM=$(extract_mem "$TMP_BASE")
    RMEM=$(extract_mem "$TMP_ROBUST")
    echo "$qname,$BMEM,$RMEM" >> "$OUT_CSV"
    echo "base=${BMEM}B robust=${RMEM}B"
done

echo ""
echo "Done. Wrote $OUT_CSV"
echo "  rows: $(($(wc -l < "$OUT_CSV") - 1))"
