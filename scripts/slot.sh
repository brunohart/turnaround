#!/usr/bin/env bash
# The daily slot. launchd calls this; it hands the day to Claude Code via the turnaround-build skill.
# One run per calendar day (a marker file keeps a second fire idle). Logs to build/slots/.
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin:$PATH"
mkdir -p build/slots
today=$(date +%F)
marker="build/slots/$today.ran"
if [ -f "$marker" ] && [ "${1:-}" != "--force" ]; then echo "slot already ran $today"; exit 0; fi
touch "$marker"
log="build/slots/$today.log"
echo "== turnaround slot $today $(date +%T) ==" | tee -a "$log"
claude -p "/turnaround-build" \
  --permission-mode acceptEdits \
  --allowedTools "Bash,Read,Edit,Write,Glob,Grep,WebFetch,WebSearch,mcp__linear__list_issues,mcp__linear__get_issue,mcp__linear__save_issue,mcp__linear__save_comment,mcp__linear__save_document,mcp__linear__list_projects,mcp__linear__list_issue_labels" \
  --output-format text 2>&1 | tee -a "$log"
echo "== slot end $(date +%T) exit ${PIPESTATUS[0]} ==" | tee -a "$log"
