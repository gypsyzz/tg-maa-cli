#!/usr/bin/env bash
set -euo pipefail

SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
STATE_DIR="$HOME/.config/maa-tg-bot"
MANAGED_FILE="$STATE_DIR/managed_profiles.txt"


# ---------------------------------------------------------------------------
# Telegram bot
# ---------------------------------------------------------------------------

echo "Removing Telegram bot service..."

systemctl --user disable --now \
    maa-telegram-bot.service \
    2>/dev/null || true


# ---------------------------------------------------------------------------
# Profile workers and timers
# ---------------------------------------------------------------------------

if [[ -f "$MANAGED_FILE" ]]; then
    while IFS= read -r name; do
        [[ -z "$name" ]] && continue

        slug="${name,,}"

        echo "Removing profile: $name"

        systemctl --user disable --now \
            "maa-$slug.timer" \
            2>/dev/null || true

        systemctl --user stop \
            "maa-$slug.service" \
            2>/dev/null || true

        rm -f \
            "$SYSTEMD_USER_DIR/maa-$slug.timer" \
            "$SYSTEMD_USER_DIR/maa-$slug.service"

    done < "$MANAGED_FILE"
fi


# ---------------------------------------------------------------------------
# Global MAA updater
# ---------------------------------------------------------------------------

echo "Removing global MAA updater..."

systemctl --user disable --now \
    maa-update.timer \
    2>/dev/null || true

systemctl --user stop \
    maa-update.service \
    2>/dev/null || true

rm -f \
    "$SYSTEMD_USER_DIR/maa-update.service" \
    "$SYSTEMD_USER_DIR/maa-update.timer"


# ---------------------------------------------------------------------------
# Remove remaining project-managed files
# ---------------------------------------------------------------------------

rm -f \
    "$SYSTEMD_USER_DIR/maa-telegram-bot.service" \
    "$MANAGED_FILE"


# ---------------------------------------------------------------------------
# Reload systemd
# ---------------------------------------------------------------------------

systemctl --user daemon-reload
systemctl --user reset-failed \
    2>/dev/null || true


echo
echo "Removed MAA Telegram bot systemd units."

echo
echo "Preserved:"
echo "  telegram_config.yaml"
echo "  profiles.yaml"
echo "  ~/.config/maa-tg-bot/alert_state.yaml"
echo "  ~/.config/maa/"
echo "  project files / virtual environment"
