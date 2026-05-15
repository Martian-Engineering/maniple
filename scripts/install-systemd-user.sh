#!/usr/bin/env bash
set -euo pipefail

# Install a user-level systemd service for running Maniple HTTP mode from this
# source checkout.

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd "${script_dir}/.." && pwd -P)"

uv_bin="${MANIPLE_UV_BIN:-$(command -v uv)}"
if [[ -z "${uv_bin}" ]]; then
    echo "uv not found in PATH. Install uv first." >&2
    exit 1
fi

host="${MANIPLE_HTTP_HOST:-127.0.0.1}"
port="${MANIPLE_HTTP_PORT:-8766}"
backend="${MANIPLE_TERMINAL_BACKEND:-tmux}"
allow_host="${MANIPLE_ALLOW_HOST:-${host}:${port}}"

config_dir="${HOME}/.config/systemd/user"
service_path="${config_dir}/maniple.service"
logs_dir="${HOME}/.maniple/logs"

mkdir -p "${config_dir}" "${logs_dir}"

cat > "${service_path}" <<EOF
[Unit]
Description=Maniple MCP Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${repo_root}
Environment=MANIPLE_TERMINAL_BACKEND=${backend}
ExecStart=${uv_bin} run --project ${repo_root} maniple --http --host ${host} --port ${port} --allow-host ${allow_host}
Restart=always
RestartSec=3
StandardOutput=append:%h/.maniple/logs/maniple.out.log
StandardError=append:%h/.maniple/logs/maniple.err.log

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now maniple

echo "Installed systemd user service:"
echo "  ${service_path}"
echo
echo "Current status:"
systemctl --user status maniple --no-pager || true
echo
echo "Useful commands:"
echo "  systemctl --user restart maniple"
echo "  journalctl --user -u maniple -n 100 --no-pager"
echo "  tail -f ~/.maniple/logs/maniple.out.log ~/.maniple/logs/maniple.err.log"
echo
echo "If you want the service to survive reboot without an active desktop login:"
echo "  loginctl enable-linger \"${USER}\""
