#!/usr/bin/env bash
set -euo pipefail

# Install launchd service for Maniple HTTP mode.

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd "${script_dir}/.." && pwd -P)"
launch_agents_dir="${HOME}/Library/LaunchAgents"
plist_path="${launch_agents_dir}/com.maniple.plist"
logs_dir="${HOME}/.maniple/logs"
stdout_log="${logs_dir}/maniple.out.log"
stderr_log="${logs_dir}/maniple.err.log"
index_cron="${MANIPLE_INDEX_CRON:-${CLAUDE_TEAM_INDEX_CRON:-1h}}"
label="com.maniple"
http_port="5111"

mkdir -p "${launch_agents_dir}" "${logs_dir}"

old_plist_path="${launch_agents_dir}/com.claude-team.plist"
old_label="com.claude-team"
if [[ -f "${old_plist_path}" ]]; then
  # Compatibility/migration: stop any previously-installed claude-team LaunchAgent.
  # Leave the old plist file in place for reversibility.
  launchctl bootout "gui/${UID}" "${old_plist_path}" 2>/dev/null || true
  launchctl unload "${old_plist_path}" 2>/dev/null || true
  launchctl disable "gui/${UID}/${old_label}" >/dev/null 2>&1 || true
  echo "Stopped old ${old_label} agent at ${old_plist_path}"
fi

if [[ -f "${plist_path}" ]]; then
  launchctl bootout "gui/${UID}" "${plist_path}" 2>/dev/null || true
  launchctl unload "${plist_path}" 2>/dev/null || true
fi

cat <<PLIST > "${plist_path}"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>${label}</string>
    <key>ProgramArguments</key>
    <array>
      <string>/usr/bin/env</string>
      <string>uv</string>
      <string>run</string>
      <string>python</string>
      <string>-m</string>
      <string>maniple_mcp</string>
      <string>--http</string>
      <string>--port</string>
      <string>${http_port}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${repo_root}</string>
    <key>EnvironmentVariables</key>
    <dict>
      <key>MANIPLE_QMD_INDEXING</key>
      <string>true</string>
      <key>MANIPLE_INDEX_CRON</key>
      <string>${index_cron}</string>
      <key>PATH</key>
      <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>StandardOutPath</key>
    <string>${stdout_log}</string>
    <key>StandardErrorPath</key>
    <string>${stderr_log}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
  </dict>
</plist>
PLIST

launchctl bootstrap "gui/${UID}" "${plist_path}"
launchctl enable "gui/${UID}/${label}" >/dev/null 2>&1 || true

echo "Installed ${label} to ${plist_path}"
echo "Logs: ${stdout_log} ${stderr_log}"
