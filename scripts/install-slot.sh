#!/usr/bin/env bash
# Install (or reinstall) the daily launchd slot: 08:45 Pacific/Auckland, every day.
# Also drops the scheduled-task stub for the Claude Code app so it appears in its task list.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
label=com.designedbybruno.turnaround-slot
plist="$HOME/Library/LaunchAgents/$label.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$here/../build/slots"
cp "$here/$label.plist" "$plist"
launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$plist"
launchctl print "gui/$(id -u)/$label" | grep -E "state|program|run interval|last exit" || true
mkdir -p "$HOME/.claude/scheduled-tasks/turnaround-daily"
cp "$here/turnaround-daily.SKILL.md" "$HOME/.claude/scheduled-tasks/turnaround-daily/SKILL.md"
echo "installed: $label fires scripts/slot.sh daily at 08:45 local; run 'bash scripts/slot.sh --force' to fire one now"
