#!/usr/bin/env bash
# team-status.sh - Formatted team overview
# Usage: team-status.sh [--json] [--project <filter>]

set -euo pipefail

JSON_OUTPUT=false
PROJECT_FILTER=""
IDLE_TIMEOUT_MINUTES=10

while [[ $# -gt 0 ]]; do
  case "$1" in
    --json)
      JSON_OUTPUT=true
      shift
      ;;
    --project)
      PROJECT_FILTER="${2:-}"
      shift 2
      ;;
    --project=*)
      PROJECT_FILTER="${1#*=}"
      shift
      ;;
    -h|--help)
      echo "Usage: team-status.sh [--json] [--project <filter>]"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -n "$PROJECT_FILTER" ]]; then
  WORKERS_JSON=$(mcporter call claude-team-http.list_workers project_filter="$PROJECT_FILTER" 2>/dev/null || echo '{"workers":[],"count":0}')
else
  WORKERS_JSON=$(mcporter call claude-team-http.list_workers 2>/dev/null || echo '{"workers":[],"count":0}')
fi

COUNT=$(echo "$WORKERS_JSON" | jq -r '.count // 0')

if [[ "$JSON_OUTPUT" == "true" ]]; then
  echo "$WORKERS_JSON"
  exit 0
fi

HEADER="Claude Team"
if [[ -n "$PROJECT_FILTER" ]]; then
  HEADER+=" (project: $PROJECT_FILTER)"
fi

if [[ "$COUNT" -eq 0 ]]; then
  echo "$HEADER - No active workers"
  exit 0
fi

if [[ "$COUNT" -eq 1 ]]; then
  echo "$HEADER - 1 worker"
else
  echo "$HEADER - $COUNT workers"
fi

echo ""

# Format each worker
echo "$WORKERS_JSON" | jq -r '.workers[] | @base64' | while read -r worker_b64; do
  worker=$(echo "$worker_b64" | base64 -d)

  name=$(echo "$worker" | jq -r '.name // "unnamed"')
  session_id=$(echo "$worker" | jq -r '.session_id // "?"' | cut -c1-8)
  main_repo=$(echo "$worker" | jq -r '.main_repo_path // .project_path // "unknown"' | xargs basename)
  annotation=$(echo "$worker" | jq -r '.coordinator_annotation // .bead // "No description"')
  msg_count=$(echo "$worker" | jq -r '.message_count // 0')
  is_idle=$(echo "$worker" | jq -r '.is_idle // false')
  agent_type=$(echo "$worker" | jq -r '.agent_type // "claude"')
  claude_session_id=$(echo "$worker" | jq -r '.claude_session_id // ""')
  project_path=$(echo "$worker" | jq -r '.project_path // ""')

  status="active"
  if [[ "$is_idle" == "true" ]]; then
    status="idle"
  elif [[ -n "$claude_session_id" && -n "$project_path" ]]; then
    project_slug=$(echo "$project_path" | sed 's|/|-|g; s|\.|-|g')
    jsonl_path="$HOME/.claude/projects/${project_slug}/${claude_session_id}.jsonl"

    if [[ -f "$jsonl_path" ]]; then
      now=$(date +%s)
      file_mtime=$(stat -f %m "$jsonl_path" 2>/dev/null || stat -c %Y "$jsonl_path" 2>/dev/null || echo "$now")
      age_seconds=$((now - file_mtime))
      age_minutes=$((age_seconds / 60))

      if [[ $age_minutes -ge $IDLE_TIMEOUT_MINUTES ]]; then
        status="idle (${age_minutes}m)"
      fi
    fi
  fi

  echo "$name [$agent_type] ($session_id)"
  echo "  repo: $main_repo"
  echo "  note: $annotation"
  echo "  msgs: $msg_count, status: $status"
  echo ""
done
