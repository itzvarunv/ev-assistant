#Sync reminders - runs on your Mac: pulls new tasks from the EV server into the Reminders app
import json
import sys
import requests
import config
import reminders

STATE = config.BASE / "data" / "last_synced_task.txt"


def main():
    if not config.EV_SERVER_URL or not config.DASHBOARD_PASSWORD:
        sys.exit("Set EV_SERVER_URL and DASHBOARD_PASSWORD in .env on this Mac.")
    STATE.parent.mkdir(exist_ok=True)
    after = int(STATE.read_text()) if STATE.exists() else 0
    r = requests.get(f"{config.EV_SERVER_URL.rstrip('/')}/api/tasks", params={"after": after},
                     auth=("ev", config.DASHBOARD_PASSWORD), timeout=30)
    r.raise_for_status()
    for t in json.loads(r.text):
        reminders.add_reminder(f"#{t['id']} {t['contact_name']}: {t['title']}",
                               f"{t['details']}\n\nWhatsApp: {t['contact_id']}", reminders.parse_due(t["due"]))
        STATE.write_text(str(t["id"]))
        print(f"Added reminder for task #{t['id']}")


if __name__ == "__main__":
    main()
