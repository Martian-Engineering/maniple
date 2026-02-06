#!/usr/bin/env bash
set -euo pipefail

# Uninstall launchd service for Maniple HTTP mode.

launch_agents_dir="${HOME}/Library/LaunchAgents"
plist_path="${launch_agents_dir}/com.maniple.plist"
label="com.maniple"

old_plist_path="${launch_agents_dir}/com.claude-team.plist"
old_label="com.claude-team"

if [[ -f "${plist_path}" ]]; then
  launchctl bootout "gui/${UID}" "${plist_path}" 2>/dev/null || true
  launchctl unload "${plist_path}" 2>/dev/null || true
  rm -f "${plist_path}"
fi

launchctl disable "gui/${UID}/${label}" >/dev/null 2>&1 || true

if [[ -f "${old_plist_path}" ]]; then
  launchctl bootout "gui/${UID}" "${old_plist_path}" 2>/dev/null || true
  launchctl unload "${old_plist_path}" 2>/dev/null || true
  launchctl disable "gui/${UID}/${old_label}" >/dev/null 2>&1 || true
fi

echo "Removed ${label} launchd service"
