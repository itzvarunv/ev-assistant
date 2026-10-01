#!/usr/bin/env bash
# Run on your Mac: pulls new EV tasks into the Reminders app every 10 minutes while the Mac is on.
set -euo pipefail
cd "$(dirname "$0")/.."
APP_DIR=$(pwd)
mkdir -p data
PLIST=~/Library/LaunchAgents/com.ev.sync-reminders.plist
sed "s|APP_DIR|$APP_DIR|g" deploy/com.ev.sync-reminders.plist > "$PLIST"
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Installed. Log: $APP_DIR/data/sync_reminders.log"
