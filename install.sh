#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
STATE_DIR="$HOME/.config/maa-tg-bot"
MANAGED_FILE="$STATE_DIR/managed_profiles.txt"

CONFIG="$ROOT/telegram_config.yaml"
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
    "$PROFILES" \
    "$ROOT/profiles.yaml.example"

if [[ "$NEEDS_EDIT" -eq 1 ]]; then
    echo
    echo "Edit the newly created configuration files, then rerun:"
    echo "  $CONFIG"
    echo "  $PROFILES"
    exit 1
fi

# Always install project dependencies into the repo-local virtual environment.
# PYTHON can select the bootstrap interpreter, but never replaces the local venv.
VENV="$ROOT/.venv"
BOOTSTRAP_PYTHON="${PYTHON:-python3}"

if [[ ! -x "$VENV/bin/python" ]]; then
    echo "Creating virtual environment: $VENV"
    "$BOOTSTRAP_PYTHON" -m venv "$VENV"
fi

PYTHON_BIN="$VENV/bin/python"
"$PYTHON_BIN" -m pip install -r "$ROOT/requirements.txt"

# Validate configuration and get configured profile names + optional MAA path.
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

from profile_store import ensure_profiles_file, load_profiles

ensure_profiles_file()
profiles = load_profiles()

if not any(name.casefold() == "yan" for name in profiles):
    raise SystemExit("The hourly container health monitor requires a YAN profile in profiles.yaml.")

maa = str(cfg.get("MAA_EXECUTABLE", "")).strip()
if not maa:
    maa = shutil.which("maa") or ""

if not maa:
    raise SystemExit(
        "Could not find maa. Install maa-cli or set "
        "MAA_EXECUTABLE in telegram_config.yaml."
    )

print(maa)

for name in profiles:
    print(name)
PY
)

if [[ "${#INFO[@]}" -lt 2 ]]; then
    echo "No configured Telegram profiles were found in $PROFILES"
    exit 1
fi

MAA_BIN="${INFO[0]}"
NAMES=("${INFO[@]:1}")

mkdir -p "$SYSTEMD_USER_DIR" "$STATE_DIR"

# Render a systemd unit template: render_unit TEMPLATE OUTPUT NAME=value ...
# Every NAME=value pair replaces the @NAME@ placeholder in the template.
render_unit() {
    "$PYTHON_BIN" - "$@" <<'PY'
import sys
from pathlib import Path

template, output, *replacements = sys.argv[1:]
text = Path(template).read_text(encoding="utf-8")

for replacement in replacements:
    placeholder, value = replacement.split("=", 1)
    text = text.replace(f"@{placeholder}@", value)

Path(output).write_text(text, encoding="utf-8")
PY
}

# Stop the bot while replacing units/code environment.
systemctl --user stop maa-telegram-bot.service 2>/dev/null || true

# Remove worker units previously managed by this project when the
# corresponding configured profile name was removed.
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
                "maa-$slug.timer" \
                "maa-$slug-schedule-check.timer" \
                2>/dev/null || true

            systemctl --user stop \
                "maa-$slug.service" \
                "maa-$slug-schedule-check.service" \
                2>/dev/null || true

            rm -f \
                "$SYSTEMD_USER_DIR/maa-$slug.timer" \
                "$SYSTEMD_USER_DIR/maa-$slug.service" \
                "$SYSTEMD_USER_DIR/maa-$slug-schedule-check.timer" \
                "$SYSTEMD_USER_DIR/maa-$slug-schedule-check.service"
        fi
    done < "$MANAGED_FILE"
fi
render_unit "$ROOT/systemd/maa-telegram-bot.service.template" "$SYSTEMD_USER_DIR/maa-telegram-bot.service" "WORKDIR=$ROOT" "PYTHON=$PYTHON_BIN" "PATH=$PATH"

for name in "${NAMES[@]}"; do
    slug="${name,,}"
    render_unit "$ROOT/systemd/maa-profile.service.template" "$SYSTEMD_USER_DIR/maa-$slug.service" "NAME=$name" "SLUG=$slug" "MAA_BIN=$MAA_BIN" "PATH=$PATH"
    render_unit "$ROOT/systemd/maa-schedule-check.service.template" "$SYSTEMD_USER_DIR/maa-$slug-schedule-check.service" "NAME=$name" "WORKDIR=$ROOT" "PYTHON=$PYTHON_BIN" "CONFIG=$CONFIG" "PATH=$PATH"
done

printf '%s\n' "${NAMES[@]}" > "$MANAGED_FILE"

# ---------------------------------------------------------------------------
# Install global MAA updater
# ---------------------------------------------------------------------------

UPDATE_SERVICE_TEMPLATE="$ROOT/systemd/maa-update.service.template"
UPDATE_TIMER_TEMPLATE="$ROOT/systemd/maa-update.timer.template"

UPDATE_SERVICE="$SYSTEMD_USER_DIR/maa-update.service"
UPDATE_TIMER="$SYSTEMD_USER_DIR/maa-update.timer"
UPDATE_TIMER_PREVIOUS_STATE="$(systemctl --user is-enabled maa-update.timer 2>/dev/null || true)"

if [[ ! -f "$UPDATE_SERVICE_TEMPLATE" ]]; then
    echo "Missing systemd template: $UPDATE_SERVICE_TEMPLATE" >&2
    exit 1
fi

if [[ ! -f "$UPDATE_TIMER_TEMPLATE" ]]; then
    echo "Missing systemd template: $UPDATE_TIMER_TEMPLATE" >&2
    exit 1
fi

echo "Installing global MAA updater..."

render_unit "$UPDATE_SERVICE_TEMPLATE" "$UPDATE_SERVICE" "MAA_BIN=$MAA_BIN" "PYTHON=$PYTHON_BIN" "WORKDIR=$ROOT" "CONFIG=$CONFIG" "PATH=$PATH"

cp \
    "$UPDATE_TIMER_TEMPLATE" \
    "$UPDATE_TIMER"

CONTAINER_HEALTH_TIMER_PREVIOUS_STATE="$(systemctl --user is-enabled maa-container-health.timer 2>/dev/null || true)"
render_unit "$ROOT/systemd/maa-container-health.service.template" "$SYSTEMD_USER_DIR/maa-container-health.service" "WORKDIR=$ROOT" "PYTHON=$PYTHON_BIN" "CONFIG=$CONFIG" "PATH=$PATH"
cp "$ROOT/systemd/maa-container-health.timer.template" "$SYSTEMD_USER_DIR/maa-container-health.timer"

systemctl --user daemon-reload

# Syntax/import validation before daemon startup.
"$PYTHON_BIN" -m py_compile \
    "$ROOT/alert_checker.py" \
    "$ROOT/maa_control.py" \
    "$ROOT/handlers.py" \
    "$ROOT/log_monitor.py" \
    "$ROOT/maa_config.py" \
    "$ROOT/i18n.py" \
    "$ROOT/profile_store.py" \
    "$ROOT/schedule_health_checker.py" \
    "$ROOT/systemd_utils.py" \
    "$ROOT/task_store.py" \
    "$ROOT/telegram_ui.py"

PYTHONPATH="$ROOT" \
MAA_BOT_CONFIG="$CONFIG" \
"$PYTHON_BIN" "$ROOT/maa_control.py" --sync-profiles

systemctl --user enable --now maa-telegram-bot.service

if [[ "$UPDATE_TIMER_PREVIOUS_STATE" == "disabled" ]]; then
    systemctl --user disable --now maa-update.timer 2>/dev/null || true
    echo "Preserved disabled MAA self-update timer."
else
    systemctl --user enable --now maa-update.timer
fi

if [[ "$CONTAINER_HEALTH_TIMER_PREVIOUS_STATE" == "disabled" ]]; then
    systemctl --user disable --now maa-container-health.timer 2>/dev/null || true
else
    systemctl --user enable --now maa-container-health.timer
fi

echo
echo "Installed:"
echo "  Telegram bot: maa-telegram-bot.service"
echo "  Global updater: maa-update.service"
echo "  Update timer: maa-update.timer"
echo "  Hourly Redroid health alerts to YAN: maa-container-health.timer"

for name in "${NAMES[@]}"; do
    slug="${name,,}"
    echo "  $name worker: maa-$slug.service -> maa run $slug -p $slug"
    echo "  $name schedule check: maa-$slug-schedule-check.service"
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
