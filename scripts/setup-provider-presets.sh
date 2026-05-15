#!/usr/bin/env bash
set -euo pipefail

# Install the claude-maniple-switch wrapper and create starter provider config
# files for ~/.maniple without overwriting existing user data.

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd "${script_dir}/.." && pwd -P)"

bin_dir="${HOME}/bin"
wrapper_src="${repo_root}/scripts/claude-maniple-switch"
wrapper_dst="${bin_dir}/claude-maniple-switch"
config_dir="${HOME}/.maniple"
config_path="${config_dir}/config.json"
env_path="${config_dir}/.env"

mkdir -p "${bin_dir}" "${config_dir}"
install -m 0755 "${wrapper_src}" "${wrapper_dst}"

if [[ ! -f "${config_path}" ]]; then
    cat > "${config_path}" <<EOF
{
  "version": 1,
  "commands": {
    "claude": null,
    "codex": null
  },
  "defaults": {
    "agent_type": "claude",
    "provider": null,
    "skip_permissions": true,
    "use_worktree": true,
    "layout": "auto"
  },
  "terminal": {
    "backend": null
  },
  "events": {
    "max_size_mb": 1,
    "recent_hours": 24,
    "stale_threshold_minutes": 10
  },
  "issue_tracker": {
    "override": null
  },
  "providers": {
    "official": {
      "command": "${wrapper_dst}",
      "env": {
        "CLAUDE_SWITCH_PROVIDER": "official"
      }
    },
    "local": {
      "command": "${wrapper_dst}",
      "env": {
        "CLAUDE_SWITCH_PROVIDER": "local"
      }
    },
    "local2": {
      "command": "${wrapper_dst}",
      "env": {
        "CLAUDE_SWITCH_PROVIDER": "local2"
      }
    },
    "local3": {
      "command": "${wrapper_dst}",
      "env": {
        "CLAUDE_SWITCH_PROVIDER": "local3"
      }
    },
    "kimi": {
      "command": "${wrapper_dst}",
      "env": {
        "CLAUDE_SWITCH_PROVIDER": "kimi"
      }
    },
    "ckimi": {
      "command": "${wrapper_dst}",
      "env": {
        "CLAUDE_SWITCH_PROVIDER": "ckimi"
      }
    },
    "minimax": {
      "command": "${wrapper_dst}",
      "env": {
        "CLAUDE_SWITCH_PROVIDER": "minimax"
      }
    },
    "aliyun": {
      "command": "${wrapper_dst}",
      "env": {
        "CLAUDE_SWITCH_PROVIDER": "aliyun"
      }
    },
    "glm": {
      "command": "${wrapper_dst}",
      "env": {
        "CLAUDE_SWITCH_PROVIDER": "glm"
      }
    },
    "kat": {
      "command": "${wrapper_dst}",
      "env": {
        "CLAUDE_SWITCH_PROVIDER": "kat"
      }
    },
    "greverse": {
      "command": "${wrapper_dst}",
      "env": {
        "CLAUDE_SWITCH_PROVIDER": "greverse"
      }
    },
    "gcs": {
      "command": "${wrapper_dst}",
      "env": {
        "CLAUDE_SWITCH_PROVIDER": "gcs"
      }
    }
  }
}
EOF
    echo "Created ${config_path}"
else
    echo "Keeping existing ${config_path}"
fi

if [[ ! -f "${env_path}" ]]; then
    cat > "${env_path}" <<'EOF'
# Fill in only the providers you actually use.
#
# Naming convention:
#   provider name "local2" -> MANIPLE_PROVIDER_LOCAL2_*
#   provider name "kimi"   -> MANIPLE_PROVIDER_KIMI_*

export MANIPLE_PROVIDER_LOCAL_API_KEY="replace-me"
export MANIPLE_PROVIDER_LOCAL_BASE_URL="https://example.local"
export MANIPLE_PROVIDER_LOCAL_MODEL="replace-me"

export MANIPLE_PROVIDER_LOCAL2_API_KEY="replace-me"
export MANIPLE_PROVIDER_LOCAL2_BASE_URL="https://example.local2"
export MANIPLE_PROVIDER_LOCAL2_MODEL="replace-me"

export MANIPLE_PROVIDER_LOCAL3_API_KEY="replace-me"
export MANIPLE_PROVIDER_LOCAL3_BASE_URL="https://example.local3"
export MANIPLE_PROVIDER_LOCAL3_MODEL="replace-me"

export MANIPLE_PROVIDER_KIMI_API_KEY="replace-me"
export MANIPLE_PROVIDER_KIMI_BASE_URL="https://api.moonshot.cn/anthropic"
export MANIPLE_PROVIDER_KIMI_MODEL="replace-me"

export MANIPLE_PROVIDER_CKIMI_API_KEY="replace-me"
export MANIPLE_PROVIDER_CKIMI_BASE_URL="https://example.ckimi"
export MANIPLE_PROVIDER_CKIMI_MODEL="replace-me"

export MANIPLE_PROVIDER_MINIMAX_API_KEY="replace-me"
export MANIPLE_PROVIDER_MINIMAX_BASE_URL="https://api.minimaxi.com/anthropic"
export MANIPLE_PROVIDER_MINIMAX_MODEL="replace-me"

export MANIPLE_PROVIDER_ALIYUN_API_KEY="replace-me"
export MANIPLE_PROVIDER_ALIYUN_BASE_URL="https://example.aliyun"
export MANIPLE_PROVIDER_ALIYUN_MODEL="replace-me"

export MANIPLE_PROVIDER_GLM_API_KEY="replace-me"
export MANIPLE_PROVIDER_GLM_BASE_URL="https://example.glm"
export MANIPLE_PROVIDER_GLM_MODEL="replace-me"

export MANIPLE_PROVIDER_KAT_API_KEY="replace-me"
export MANIPLE_PROVIDER_KAT_BASE_URL="https://example.kat"
export MANIPLE_PROVIDER_KAT_MODEL="replace-me"

export MANIPLE_PROVIDER_GREVERSE_API_KEY="replace-me"
export MANIPLE_PROVIDER_GREVERSE_BASE_URL="https://example.greverse"
export MANIPLE_PROVIDER_GREVERSE_MODEL="replace-me"

export MANIPLE_PROVIDER_GCS_API_KEY="replace-me"
export MANIPLE_PROVIDER_GCS_BASE_URL="https://example.gcs"
export MANIPLE_PROVIDER_GCS_MODEL="replace-me"
EOF
    chmod 0600 "${env_path}"
    echo "Created ${env_path}"
else
    echo "Keeping existing ${env_path}"
fi

echo
echo "Installed wrapper:"
echo "  ${wrapper_dst}"
echo
echo "Next steps:"
echo "  1. Edit ${config_path} and keep only the providers you want."
echo "  2. Edit ${env_path} and replace the placeholder values."
echo "  3. Optional: set a default provider:"
echo "       uv run maniple config set defaults.provider local"
echo "  4. If running under systemd:"
echo "       systemctl --user restart maniple"
