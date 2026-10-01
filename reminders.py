#Reminders - macOS Reminders app (only works when running on a Mac; the server uses WhatsApp instead)
import subprocess
import sys
from datetime import datetime
import config

# Values are passed as argv, never pasted into the script, so message text can't inject AppleScript.
SCRIPT = """
on run argv
    set listName to item 1 of argv
    set theTitle to item 2 of argv
    set theNotes to item 3 of argv
    set secondsFromNow to (item 4 of argv) as integer
    tell application "Reminders"
        if not (exists list listName) then make new list with properties {name:listName}
        tell list listName
            set r to make new reminder with properties {name:theTitle, body:theNotes}
            if secondsFromNow > 0 then set due date of r to (current date) + secondsFromNow
        end tell
    end tell
end run
"""


def parse_due(text):
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(text).strip()[:16], fmt)
        except ValueError:
            pass
    return None


def add_reminder(title, notes="", due=None):
    if sys.platform != "darwin":
        return False
    seconds = int((due - datetime.now()).total_seconds()) if due and due > datetime.now() else 0
    try:
        subprocess.run(["osascript", "-e", SCRIPT, config.REMINDERS_LIST, title, notes, str(seconds)],
                       check=True, capture_output=True, timeout=30)
        return True
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        print(f"[reminders] Couldn't reach the Reminders app: {e}")
        return False
