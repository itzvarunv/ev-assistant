#Tasks - things only the owner can decide; EV collects the details and hands them over
import config
import reminders


def _print_notice(db, text):
    print(f"\n[to {config.OWNER_NAME}]\n{text}\n")


# server.py swaps this for a WhatsApp message to OWNER_PHONE
notify_owner = _print_notice


def create_task(db, contact_id, name, title, details, due_text=None):
    due = reminders.parse_due(due_text)
    cur = db.execute(
        "INSERT INTO tasks (contact_id, contact_name, title, details, due) VALUES (?, ?, ?, ?, ?)",
        (contact_id, name, title, details, due.isoformat(" ", "minutes") if due else None))
    db.commit()
    task_id = cur.lastrowid
    notice = (f"📌 Task #{task_id} from {name} ({contact_id})\n{title}\n{details}"
              + (f"\nWhen: {due:%a %d %b, %H:%M}" if due else "")
              + f"\n\nReply with:\nreply {task_id} <your answer>\ndone {task_id}")
    notify_owner(db, notice)
    reminders.add_reminder(f"#{task_id} {name}: {title}", details, due)
    return task_id


def open_tasks(db):
    return db.execute("SELECT * FROM tasks WHERE status = 'open' ORDER BY id").fetchall()


def get_task(db, task_id):
    return db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()


def close_task(db, task_id):
    db.execute("UPDATE tasks SET status = 'done' WHERE id = ?", (task_id,))
    db.commit()
