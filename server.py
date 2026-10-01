#Server - receives WhatsApp webhooks 24/7 and answers them
import queue
import sys
import threading
import time
import traceback
from pathlib import Path
from flask import Flask, request
from waitress import serve
import brain
import dashboard
import config
import ingest
import owner
import planner
import tasks
import whatsapp
from db import get_connection, should_stay_quiet

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024   # dashboard uploads
app.register_blueprint(dashboard.bp)
INCOMING = config.BASE / "data" / "incoming"   # photos from contacts, deleted after EV reads them
jobs = queue.Queue()   # Meta wants a fast 200; everything slow happens in background threads


@app.get("/webhook")
def verify():
    if (request.args.get("hub.mode") == "subscribe"
            and request.args.get("hub.verify_token") == config.WA_VERIFY_TOKEN):
        return request.args.get("hub.challenge", ""), 200
    return "forbidden", 403


@app.post("/webhook")
def incoming():
    if not whatsapp.valid_signature(request.get_data(), request.headers.get("X-Hub-Signature-256")):
        return "bad signature", 401
    payload = request.get_json(silent=True) or {}
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            names = {c.get("wa_id"): c.get("profile", {}).get("name", "") for c in value.get("contacts", [])}
            for msg in value.get("messages", []):
                jobs.put(("message", msg, names.get(msg.get("from"), "")))
            # Coexistence: something YOU sent from the WhatsApp Business app on your phone
            for echo in value.get("message_echoes", []):
                jobs.put(("echo", echo, ""))
    return "ok", 200


@app.get("/health")
def health():
    return "ok", 200


def notify_owner(db, text):
    if not config.OWNER_PHONE:
        db.execute("INSERT INTO owner_outbox (text) VALUES (?)", (text,))
        db.commit()
        return
    try:
        whatsapp.send_text(config.OWNER_PHONE, text)
    except whatsapp.WhatsAppError:
        # WhatsApp only allows free messages within 24h of your last message to EV.
        # Keep it and deliver the next time you message EV.
        db.execute("INSERT INTO owner_outbox (text) VALUES (?)", (text,))
        db.commit()


def flush_owner_outbox(db):
    for row in db.execute("SELECT id, text FROM owner_outbox ORDER BY id").fetchall():
        whatsapp.send_text(config.OWNER_PHONE, row["text"])
        db.execute("DELETE FROM owner_outbox WHERE id = ?", (row["id"],))
    db.commit()


OWNER_COMMANDS = {"tasks", "reply", "done", "docs", "share", "unshare", "skip", "unskip", "skipped", "on", "off", "help"}


def handle_owner(db, msg):
    """You, messaging EV: commands, file uploads, or your personal assistant (schedule + questions)."""
    planner.owner_wrote(db)
    flush_owner_outbox(db)
    kind = msg.get("type")
    caption = (msg.get(kind, {}).get("caption") or "").strip().lower() if kind in ("document", "image") else ""
    if kind == "reaction":
        return                                  # a 👍 reaction just keeps the 24h window open
    if kind == "document" or (kind == "image" and caption.split()[:1] in (["save"], ["public"], ["private"])):
        media = msg[kind]
        private = caption.startswith("private")
        whatsapp.send_text(config.OWNER_PHONE, "📥 Got it, reading the file...")
        path = whatsapp.download_media(media["id"], config.INBOX if private else config.PUBLIC_DIR,
                                       media.get("filename"))
        result = ingest.ingest_file(db, path, public=not private)
        if result:
            where = "private (use: share <id> <phone>)" if private else "public - anyone can ask for it"
            reply = f"Saved as document [{result[0]}] {result[1]} → {where}"
        else:
            reply = "I can't read that file type yet (PDF, images, txt/md/csv work)."
    elif kind == "image":                       # e.g. a photo of your timetable or a test notice
        path = whatsapp.download_media(msg["image"]["id"], INCOMING)
        try:
            reply = planner.handle(db, msg["image"].get("caption", ""), [str(path)])
        finally:
            Path(path).unlink(missing_ok=True)
    elif kind == "text":
        text = msg["text"].get("body", "")
        first = text.strip().split()[:1]
        if first and first[0].lower() in OWNER_COMMANDS:
            reply = owner.handle_command(db, text, whatsapp.send_text)
        else:
            reply = planner.handle(db, text)
    else:
        reply = "I can read text and photos for now."
    whatsapp.send_text(config.OWNER_PHONE, reply)


def remind_owner(db, text):
    try:
        whatsapp.send_text(config.OWNER_PHONE, text)
    except whatsapp.WhatsAppError:
        # Outside WhatsApp's 24h window: deliver when you next write, clearly marked as late.
        notify_owner(db, f"⚠️ Late - I couldn't reach you at the time (WhatsApp's 24h limit):\n{text}")


def planner_clock():
    """Reminders, the morning summary and the 24h keep-alive nudge."""
    db = get_connection()
    while True:
        try:
            planner.tick(db, lambda text: remind_owner(db, text))
        except Exception:
            traceback.print_exc()
        time.sleep(20)


def first_time(db, msg_id):
    """WhatsApp retries webhooks; handle each message once."""
    if db.execute("SELECT 1 FROM seen_messages WHERE msg_id = ?", (msg_id,)).fetchone():
        return False
    db.execute("INSERT INTO seen_messages VALUES (?)", (msg_id,))
    db.commit()
    return True


def owner_replied(db, echo):
    """You answered someone yourself: EV backs off that chat and remembers what you said."""
    contact = echo.get("to", "")
    db.execute("INSERT OR REPLACE INTO takeovers VALUES (?, ?)",
               (contact, time.time() + config.TAKEOVER_HOURS * 3600))
    db.execute("DELETE FROM pending_messages WHERE contact_id = ?", (contact,))
    text = echo.get("text", {}).get("body") or f"[{echo.get('type', 'message')}]"
    db.execute("INSERT INTO messages (contact_id, role, text) VALUES (?, 'assistant', ?)",
               (contact, f"[{config.OWNER_NAME} replied personally] {text}"))
    db.commit()


def handle(db, kind, msg, name):
    if not first_time(db, msg.get("id", "")):
        return
    if kind == "echo":
        return owner_replied(db, msg)
    sender = msg.get("from", "")
    if config.OWNER_PHONE and sender == config.OWNER_PHONE:
        return handle_owner(db, msg)
    if db.execute("SELECT 1 FROM skip_contacts WHERE contact_id = ?", (sender,)).fetchone():
        return
    kind, image_path = msg.get("type"), None
    if kind == "text":
        text = msg["text"].get("body", "")
    elif kind in ("image", "sticker"):
        image_path = str(whatsapp.download_media(msg[kind]["id"], INCOMING))
        text = msg[kind].get("caption", "") if kind == "image" else "(sent a sticker)"
    else:
        text = f"(sent a {kind} - you can't open that type yet, ask them to type it or send a photo)"
    db.execute("INSERT INTO pending_messages (contact_id, name, text, due_at, image_path) VALUES (?, ?, ?, ?, ?)",
               (sender, name or sender, text, time.time() + config.REPLY_DELAY_SECONDS, image_path))
    db.commit()


def worker():
    """Fast bookkeeping only: queue messages, record your takeovers, run owner commands."""
    db = get_connection()
    while True:
        kind, msg, name = jobs.get()
        try:
            handle(db, kind, msg, name)
        except Exception:
            traceback.print_exc()


def answer_due(db):
    now = time.time()
    contacts = db.execute("SELECT DISTINCT contact_id FROM pending_messages WHERE due_at <= ?", (now,)).fetchall()
    for c in contacts:
        contact = c["contact_id"]
        rows = db.execute("SELECT id, name, text, image_path FROM pending_messages WHERE contact_id = ? ORDER BY id",
                          (contact,)).fetchall()
        images = [r["image_path"] for r in rows if r["image_path"]]
        db.execute("DELETE FROM pending_messages WHERE contact_id = ? AND id <= ?", (contact, rows[-1]["id"]))
        db.commit()
        try:
            if should_stay_quiet(db, contact, now):
                continue
            # Several quick messages from one person get a single reply.
            out = brain.handle_message(db, contact, rows[-1]["name"],
                                       "\n".join(r["text"] for r in rows if r["text"]), images)
        finally:
            for path in images:   # other people's photos aren't kept once read
                Path(path).unlink(missing_ok=True)
        # You may have jumped in while the model was thinking - then your answer wins.
        if should_stay_quiet(db, contact, time.time()):
            continue
        whatsapp.send_text(contact, out["reply"])
        if out["file"]:
            whatsapp.send_document(contact, out["file"])


def replier():
    """Answers people once REPLY_DELAY_SECONDS have passed without you replying."""
    db = get_connection()
    while True:
        try:
            answer_due(db)
        except Exception:
            traceback.print_exc()
        time.sleep(5)


def folder_watcher():
    """Picks up files you copy into public/ or inbox/ directly on the server."""
    db = get_connection()
    while True:
        try:
            ingest.ingest_all(db)
        except Exception:
            traceback.print_exc()
        time.sleep(60)


def main():
    missing = [k for k in ("WA_TOKEN", "WA_PHONE_NUMBER_ID", "WA_VERIFY_TOKEN", "WA_APP_SECRET")
               if not getattr(config, k)]
    if missing:
        sys.exit(f"Missing in .env: {', '.join(missing)} (see .env.example)")
    tasks.notify_owner = notify_owner
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=replier, daemon=True).start()
    if config.OWNER_PHONE:
        threading.Thread(target=planner_clock, daemon=True).start()
    threading.Thread(target=folder_watcher, daemon=True).start()
    print(f"EV listening on 127.0.0.1:{config.PORT}")
    serve(app, host="127.0.0.1", port=config.PORT)


if __name__ == "__main__":
    main()
