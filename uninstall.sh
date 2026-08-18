#!/usr/bin/env bash
set -euo pipefail

SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
STATE_DIR="$HOME/.config/maa-tg-bot"
MANAGED_FILE="$STATE_DIR/managed_profiles.txt"

systemctl --user disable --now \
    maa-telegram-bot.service 2>/dev/null || true

if [[ -f "$MANAGED_FILE" ]]; then
    while IFS= read -r name; do
        [[ -z "$name" ]] && continue

        slug="${name,,}"

        systemctl --user disable --now \
            "maa-$slug.timer" 2>/dev/null || true

        systemctl --user stop \
            "maa-$slug.service" 2>/dev/null || true

        rm -f \
            "$SYSTEMD_USER_DIR/maa-$slug.timer" \
            "$SYSTEMD_USER_DIR/maa-$slug.service"
    done < "$MANAGED_FILE"
fi

rm -f "$SYSTEMD_USER_DIR/maa-telegram-bot.service"
rm -f "$MANAGED_FILE"

systemctl --user daemon-reload
systemctl --user reset-failed 2>/dev/null || true

echo "Removed MAA Telegram bot systemd units."
echo
echo "Preserved:"
echo "  telegram_config.yaml"
echo "  authorized_chats.yaml"
echo "  profiles.yaml"
echo "  ~/.config/maa/"
echo "  project files / virtual environment"
