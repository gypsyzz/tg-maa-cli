#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
STATE_DIR="$HOME/.config/maa-tg-bot"
MANAGED_FILE="$STATE_DIR/managed_profiles.txt"

CONFIG="$ROOT/telegram_config.yaml"
AUTH="$ROOT/authorized_chats.yaml"
PROFILES="$ROOT/profiles.yaml"

NEEDS_EDIT=0

create_if_missing() {
    local target="$1"
    local example="$2"

    if [[ ! -f "$target" ]]; then
        cp "$example" "$target"
        echo "Created: $target"
        NEEDS_EDIT=1
    fi
}

create_if_missing \
    "$CONFIG" \
    "$ROOT/telegram_config.yaml.example"

create_if_missing \
    "$AUTH" \
    "$ROOT/authorized_chats.yaml.example"

create_if_missing \
    "$PROFILES" \
    "$ROOT/profiles.yaml.example"

if [[ "$NEEDS_EDIT" -eq 1 ]]; then
    echo
    echo "Edit the newly created configuration files, then rerun:"
    echo "  $CONFIG"
    echo "  $AUTH"
    echo "  $PROFILES"
    exit 1
fi

# Python selection:
# 1) explicit PYTHON=...
# 2) currently active venv
# 3) repo-local .venv (create if needed)
if [[ -n "${PYTHON:-}" ]]; then
    PYTHON_BIN="$PYTHON"
elif [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python" ]]; then
    PYTHON_BIN="$VIRTUAL_ENV/bin/python"
else
    VENV="$ROOT/.venv"

    if [[ ! -x "$VENV/bin/python" ]]; then
        echo "Creating virtual environment: $VENV"
        python3 -m venv "$VENV"
    fi

    PYTHON_BIN="$VENV/bin/python"
fi

"$PYTHON_BIN" -m pip install -r "$ROOT/requirements.txt"

# Validate configuration and get authorized profile names + optional MAA path.
mapfile -t INFO < <(
    PYTHONPATH="$ROOT" \
    MAA_BOT_CONFIG="$CONFIG" \
    "$PYTHON_BIN" - "$CONFIG" <<'PY'
import shutil
import sys
from pathlib import Path

import yaml

config_path = Path(sys.argv[1])
cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

token = str(cfg.get("TOKEN", "")).strip()
if not token or token == "PUT_BOT_TOKEN_HERE":
    raise SystemExit("Set TOKEN in telegram_config.yaml first.")

from maa_config import AUTHORIZED_BY_NAME
from profile_store import ensure_profiles_file, load_profiles

ensure_profiles_file()
load_profiles()

maa = str(cfg.get("MAA_EXECUTABLE", "")).strip()
if not maa:
    maa = shutil.which("maa") or ""

if not maa:
    raise SystemExit(
        "Could not find maa. Install maa-cli or set "
        "MAA_EXECUTABLE in telegram_config.yaml."
    )

print(maa)

for name in AUTHORIZED_BY_NAME:
    print(name)
PY
)

if [[ "${#INFO[@]}" -lt 2 ]]; then
    echo "No authorized Telegram chats were found in $AUTH"
    exit 1
fi

MAA_BIN="${INFO[0]}"
NAMES=("${INFO[@]:1}")

mkdir -p "$SYSTEMD_USER_DIR" "$STATE_DIR"

render_bot_unit() {
    "$PYTHON_BIN" - \
        "$ROOT/systemd/maa-telegram-bot.service.template" \
        "$SYSTEMD_USER_DIR/maa-telegram-bot.service" \
        "$ROOT" \
        "$PYTHON_BIN" \
        "$PATH" <<'PY'
import sys
from pathlib import Path

template, output, root, python, path = sys.argv[1:]
text = Path(template).read_text(encoding="utf-8")
text = (
    text
    .replace("@WORKDIR@", root)
    .replace("@PYTHON@", python)
    .replace("@PATH@", path)
)
Path(output).write_text(text, encoding="utf-8")
PY
}

render_profile_unit() {
    local name="$1"
    local slug="${name,,}"

    "$PYTHON_BIN" - \
        "$ROOT/systemd/maa-profile.service.template" \
        "$SYSTEMD_USER_DIR/maa-$slug.service" \
        "$name" \
        "$slug" \
        "$MAA_BIN" \
        "$PATH" <<'PY'
import sys
from pathlib import Path

template, output, name, slug, maa_bin, path = sys.argv[1:]
text = Path(template).read_text(encoding="utf-8")
text = (
    text
    .replace("@NAME@", name)
    .replace("@SLUG@", slug)
    .replace("@MAA_BIN@", maa_bin)
    .replace("@PATH@", path)
)
Path(output).write_text(text, encoding="utf-8")
PY
}

# Stop the bot while replacing units/code environment.
systemctl --user stop maa-telegram-bot.service 2>/dev/null || true

# Remove worker units previously managed by this project when the
# corresponding authorization/profile name was removed.
if [[ -f "$MANAGED_FILE" ]]; then
    while IFS= read -r old_name; do
        [[ -z "$old_name" ]] && continue

        keep=0

        for name in "${NAMES[@]}"; do
            if [[ "${name,,}" == "${old_name,,}" ]]; then
                keep=1
                break
            fi
        done

        if [[ "$keep" -eq 0 ]]; then
            slug="${old_name,,}"

            systemctl --user disable --now \
                "maa-$slug.timer" 2>/dev/null || true

            systemctl --user stop \
                "maa-$slug.service" 2>/dev/null || true

            rm -f \
                "$SYSTEMD_USER_DIR/maa-$slug.timer" \
                "$SYSTEMD_USER_DIR/maa-$slug.service"
        fi
    done < "$MANAGED_FILE"
fi
render_bot_unit

for name in "${NAMES[@]}"; do
    render_profile_unit "$name"
done

printf '%s\n' "${NAMES[@]}" > "$MANAGED_FILE"

# ---------------------------------------------------------------------------
# Install global MAA updater
# ---------------------------------------------------------------------------

UPDATE_SERVICE_TEMPLATE="$ROOT/systemd/maa-update.service.template"
UPDATE_TIMER_TEMPLATE="$ROOT/systemd/maa-update.timer.template"

UPDATE_SERVICE="$SYSTEMD_USER_DIR/maa-update.service"
UPDATE_TIMER="$SYSTEMD_USER_DIR/maa-update.timer"

if [[ ! -f "$UPDATE_SERVICE_TEMPLATE" ]]; then
    echo "Missing systemd template: $UPDATE_SERVICE_TEMPLATE" >&2
    exit 1
fi

if [[ ! -f "$UPDATE_TIMER_TEMPLATE" ]]; then
    echo "Missing systemd template: $UPDATE_TIMER_TEMPLATE" >&2
    exit 1
fi

echo "Installing global MAA updater..."

sed \
    -e "s|__MAA_BIN__|$MAA_BIN|g" \
    "$UPDATE_SERVICE_TEMPLATE" \
    > "$UPDATE_SERVICE"

cp \
    "$UPDATE_TIMER_TEMPLATE" \
    "$UPDATE_TIMER"

systemctl --user daemon-reload

# Syntax/import validation before daemon startup.
"$PYTHON_BIN" -m py_compile \
    "$ROOT/maa_control.py" \
    "$ROOT/handlers.py" \
    "$ROOT/log_monitor.py" \
    "$ROOT/maa_config.py" \
    "$ROOT/i18n.py" \
    "$ROOT/profile_store.py" \
    "$ROOT/systemd_utils.py" \
    "$ROOT/task_store.py" \
    "$ROOT/telegram_ui.py"

PYTHONPATH="$ROOT" \
MAA_BOT_CONFIG="$CONFIG" \
"$PYTHON_BIN" "$ROOT/maa_control.py" --sync-profiles

systemctl --user enable --now maa-telegram-bot.service
systemctl --user enable --now maa-update.timer

echo
echo "Installed:"
echo "  Telegram bot: maa-telegram-bot.service"
echo "  Global updater: maa-update.service"
echo "  Update timer: maa-update.timer"

for name in "${NAMES[@]}"; do
    slug="${name,,}"
    echo "  $name worker: maa-$slug.service -> maa run $slug -p $slug"
done

echo
echo "Status:"
systemctl --user --no-pager --full status \
    maa-telegram-bot.service || true

echo
echo "Timers:"
systemctl --user --no-pager list-timers \
    'maa-*.timer' --all || true

# Warn about missing MAA task/profile files without preventing install.
MAA_CONFIG_DIR="$("$MAA_BIN" dir config 2>/dev/null || true)"

if [[ -n "$MAA_CONFIG_DIR" && -d "$MAA_CONFIG_DIR" ]]; then
    echo
    echo "MAA configuration checks:"

    for name in "${NAMES[@]}"; do
        slug="${name,,}"

        task="$MAA_CONFIG_DIR/tasks/$slug.json"

        if [[ -f "$task" ]]; then
            echo "  OK task:    $task"
        else
            echo "  WARNING missing task JSON: $task"
        fi

        if [[ -f "$MAA_CONFIG_DIR/profiles/$slug.json" ]]; then
            echo "  OK profile: $MAA_CONFIG_DIR/profiles/$slug.json"
        elif [[ -f "$MAA_CONFIG_DIR/profiles/$slug.toml" ]]; then
            echo "  OK profile: $MAA_CONFIG_DIR/profiles/$slug.toml"
        else
            echo "  WARNING missing MAA profile: $slug"
        fi
    done
fi

if command -v loginctl >/dev/null 2>&1; then
    linger="$(
        loginctl show-user "$USER" \
            -p Linger --value 2>/dev/null || true
    )"

    if [[ "$linger" != "yes" ]]; then
        echo
        echo "For user services/timers to start at boot before login, run once:"
        echo "  sudo loginctl enable-linger $USER"
    fi
fi

echo
echo "Installation complete."