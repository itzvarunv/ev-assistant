#Owner commands - you control EV by messaging it from your own WhatsApp
import config
import tasks

HELP = """Your schedule (just write normally):
"Math test Friday 10am", "gym every Monday 6pm", or send a photo of a timetable.
today / tomorrow / week - what's coming up
cancel <id> - remove something

EV commands:
tasks - list open tasks
reply <id> <message> - send your answer to that person and close the task
done <id> - close a task without replying
docs - list documents
share <doc id> <phone or *> / unshare <doc id> <phone or *>
skip <phone> / unskip <phone> - EV never answers this person (family, close friends)
skipped - list them
off / on - pause or resume EV for everyone
📎 Send me a photo/PDF - I add it to public/ (anyone can get it).
Caption it "private" to keep it private instead."""


def handle_command(db, text, send_text):
    parts = text.strip().split(maxsplit=2)
    cmd = parts[0].lower() if parts else ""

    if cmd == "tasks":
        rows = tasks.open_tasks(db)
        if not rows:
            return "No open tasks 🎉"
        return "\n\n".join(f"#{t['id']} {t['contact_name']}: {t['title']}"
                           + (f" (due {t['due']})" if t["due"] else "") + f"\n{t['details']}" for t in rows)

    if cmd in ("reply", "done") and len(parts) >= 2 and parts[1].lstrip("#").isdigit():
        task = tasks.get_task(db, int(parts[1].lstrip("#")))
        if not task:
            return "No task with that number."
        if cmd == "reply":
            if len(parts) < 3:
                return "Usage: reply <id> <message>"
            message = f"Message from {config.OWNER_NAME}: {parts[2]}"
            send_text(task["contact_id"], message)
            db.execute("INSERT INTO messages (contact_id, role, text) VALUES (?, 'assistant', ?)",
                       (task["contact_id"], message))
        tasks.close_task(db, task["id"])
        return f"✅ Task #{task['id']} closed" + (f" and your reply was sent to {task['contact_name']}." if cmd == "reply" else ".")

    if cmd == "docs":
        rows = db.execute("""
            SELECT d.doc_id, d.title, GROUP_CONCAT(p.contact_id, ', ') AS shared
            FROM documents d LEFT JOIN doc_permissions p ON p.doc_id = d.doc_id
            GROUP BY d.doc_id ORDER BY d.doc_id""").fetchall()
        return "\n".join(f"[{r['doc_id']}] {r['title']} → {r['shared'] or 'private'}" for r in rows) or "No documents yet."

    if cmd in ("share", "unshare") and len(parts) == 3 and parts[1].isdigit():
        who = parts[2].lstrip("+")
        if cmd == "share":
            db.execute("INSERT OR IGNORE INTO doc_permissions VALUES (?, ?)", (int(parts[1]), who))
        else:
            db.execute("DELETE FROM doc_permissions WHERE doc_id = ? AND contact_id = ?", (int(parts[1]), who))
        db.commit()
        return f"Document {parts[1]} {'shared with' if cmd == 'share' else 'no longer shared with'} {who}."

    if cmd in ("skip", "unskip") and len(parts) >= 2:
        who = "".join(ch for ch in " ".join(parts[1:]) if ch.isdigit())   # "+91 98765 43210" -> 919876543210
        if cmd == "skip":
            db.execute("INSERT OR IGNORE INTO skip_contacts VALUES (?)", (who,))
        else:
            db.execute("DELETE FROM skip_contacts WHERE contact_id = ?", (who,))
        db.commit()
        return f"EV will {'never answer' if cmd == 'skip' else 'answer again'} {who}."

    if cmd == "skipped":
        rows = db.execute("SELECT contact_id FROM skip_contacts ORDER BY contact_id").fetchall()
        return "\n".join(r["contact_id"] for r in rows) or "Nobody is on the skip list."

    if cmd in ("on", "off"):
        db.execute("INSERT OR REPLACE INTO settings VALUES ('ev_on', ?)", ("1" if cmd == "on" else "0",))
        db.commit()
        return "EV is back on ✅" if cmd == "on" else "EV is paused ⏸ - nobody gets auto-replies until you send 'on'."

    return HELP
