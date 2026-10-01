#Planner - EV's personal side: remembers your schedule, reminds you on time, answers quick questions
import json
import time
from datetime import datetime, timedelta
import brain
import config
import llm
import websearch

FMT = "%Y-%m-%d %H:%M"
REPEATS = {"daily": "every day", "weekdays": "Mon-Fri", "weekly": "every week"}
KEEP_ALIVE_TIP = "\n\n(Reply 👍 once a day so WhatsApp lets me keep reminding you.)"

PROMPT = """You are EV, the personal assistant of {owner}. You are chatting with {owner} directly on WhatsApp.
Current time: {now:%A %Y-%m-%d %H:%M}.
{owner}'s upcoming schedule:
{schedule}

Answer ONLY with a JSON object:
{{
  "action": "add" | "cancel" | "search" | "answer",
  "events": [{{"title": "short name", "start": "YYYY-MM-DD HH:MM", "remind_before_min": 30,
              "repeat": null or "daily" or "weekdays" or "weekly"}}],
  "cancel_ids": [ids from the schedule above],
  "search_query": "web search query",
  "reply": "short, friendly WhatsApp reply"
}}
- "add": the message (or photo) mentions anything with a date or time - tests, exams, classes, deadlines,
  appointments, meetings, things to do. One entry per occurrence, or use "repeat": "daily" (every day),
  "weekdays" (Monday-Friday, e.g. school or college classes) or "weekly" (e.g. every Monday).
  Work out words like "tomorrow", "Friday", "next week" from the current time. No time given -> 09:00.
  remind_before_min is 30 unless {owner} asks for something else.
- "cancel": {owner} wants to remove something from the schedule.
- "search": you CAN search the web. Use it for news, weather, scores, prices, opening hours, anything current or
  that you are not sure about. Never say you lack real-time access - search instead. Give a precise search_query.
- "answer": everything else. Be short and practical."""


def local_now():
    return brain.now().replace(tzinfo=None, second=0, microsecond=0)


def parse_time(text):
    try:
        return datetime.strptime(str(text).strip()[:16].replace("T", " "), FMT)
    except ValueError:
        return None


def next_occurrence(start, repeat):
    if repeat == "weekly":
        return start + timedelta(days=7)
    nxt = start + timedelta(days=1)
    while repeat == "weekdays" and nxt.weekday() >= 5:     # skip Saturday and Sunday
        nxt += timedelta(days=1)
    return nxt


def nice(dt):
    return dt.strftime("%a %d %b, %H:%M")


def upcoming(db, until=None):
    rows = db.execute("SELECT * FROM events WHERE status = 'upcoming' ORDER BY start_at").fetchall()
    return [r for r in rows if until is None or parse_time(r["start_at"]) < until]


def schedule_text(rows):
    return "\n".join(f"#{r['id']} {r['title']} - {nice(parse_time(r['start_at']))}"
                     + (f" ({REPEATS.get(r['repeat'], r['repeat'])})" if r["repeat"] else "")
                     for r in rows) or "nothing scheduled"


def add_events(db, events, now):
    saved, rejected = [], []
    for e in events:
        start = parse_time(e.get("start"))
        title = str(e.get("title") or "").strip()[:80]
        repeat = e.get("repeat") if e.get("repeat") in REPEATS else None
        try:
            before = max(0, min(int(e.get("remind_before_min", 30)), 7 * 24 * 60))
        except (TypeError, ValueError):
            before = 30
        if not start or not title:
            continue
        if start < now and not repeat:
            rejected.append(f"{title} ({nice(start)} has already passed)")
            continue
        if repeat == "weekdays" and start.weekday() >= 5:
            start = next_occurrence(start, repeat)
        while start < now:                      # a repeating event starting in the past: next occurrence
            start = next_occurrence(start, repeat)
        cur = db.execute("INSERT INTO events (title, start_at, remind_before_min, repeat) VALUES (?, ?, ?, ?)",
                         (title, start.strftime(FMT), before, repeat))
        saved.append((cur.lastrowid, title, start, before, repeat))
    db.commit()
    lines = []
    for event_id, title, start, before, repeat in saved:
        when = f"{nice(start)}" + (f", {REPEATS[repeat]}" if repeat else "")
        alert = f"reminders at {(start - timedelta(minutes=before)):%H:%M} and {start:%H:%M}" if before else f"reminder at {start:%H:%M}"
        lines.append(f"✅ #{event_id} {title} - {when} ({alert})")
    if rejected:
        lines.append("⚠️ Not saved, tell me the right date: " + "; ".join(rejected))
    return "\n".join(lines) or "I couldn't find a date and time in that - could you say it like 'Math test Friday 10am'?"


def cancel_events(db, ids):
    done = []
    for i in ids:
        if isinstance(i, int) or str(i).isdigit():
            cur = db.execute("UPDATE events SET status = 'cancelled' WHERE id = ? AND status = 'upcoming'", (int(i),))
            if cur.rowcount:
                done.append(f"#{i}")
    db.commit()
    return f"🗑 Cancelled {', '.join(done)}." if done else "I couldn't find that in your schedule. Send 'week' to see it."


def quick_command(db, text, now):
    """Exact commands that never need the AI."""
    words = text.lower().split()
    if not words:
        return None
    if words[0] in ("today", "tomorrow"):
        day = now.date() + timedelta(days=0 if words[0] == "today" else 1)
        rows = [r for r in upcoming(db) if parse_time(r["start_at"]).date() == day]
        return f"📅 {words[0].title()}:\n" + schedule_text(rows)
    if words[0] in ("week", "schedule", "upcoming", "list"):
        return "📅 Next 7 days:\n" + schedule_text(upcoming(db, until=now + timedelta(days=7)))
    if words[0] in ("cancel", "delete", "remove") and len(words) == 2 and words[1].lstrip("#").isdigit():
        return cancel_events(db, [words[1].lstrip("#")])
    if words[0] in ("👍", "ok", "okay", "k", "thanks", "thank"):
        return "👍"
    return None


def handle(db, text, images=()):
    """A message from the owner. Returns EV's reply."""
    now = local_now()
    for path in images:
        text = f"[Photo you sent shows: {brain.describe_photo(path)}]\n{text}".strip()
    reply = quick_command(db, text, now)
    if reply:
        return reply

    history = db.execute("SELECT role, text FROM messages WHERE contact_id = ? ORDER BY id DESC LIMIT 6",
                         (config.OWNER_PHONE,)).fetchall()
    messages = [{"role": "system", "content": PROMPT.format(
        owner=config.OWNER_NAME, now=now, schedule=schedule_text(upcoming(db)))}]
    messages += [{"role": h["role"], "content": h["text"]} for h in reversed(history)]
    messages.append({"role": "user", "content": text})
    out = brain.ask_model(messages)
    if out.get("action") == "search" and out.get("search_query"):
        results = websearch.research(db, str(out["search_query"])[:200]) or "no results found"
        messages += [{"role": "assistant", "content": json.dumps(out)},
                     {"role": "user", "content": brain.AFTER_SEARCH.format(query=out["search_query"], results=results)}]
        out = brain.ask_model(messages)

    action = out.get("action")
    if action == "add" and isinstance(out.get("events"), list):
        reply = add_events(db, out["events"], now)          # confirmation is written by code, so dates are exact
    elif action == "cancel" and isinstance(out.get("cancel_ids"), list):
        reply = cancel_events(db, out["cancel_ids"])
    else:
        reply = str(out.get("reply") or "Sorry, I didn't get that. Try 'Math test Friday 10am' or 'week'.")

    db.executemany("INSERT INTO messages (contact_id, role, text) VALUES (?, ?, ?)",
                   [(config.OWNER_PHONE, "user", text), (config.OWNER_PHONE, "assistant", reply)])
    db.commit()
    return reply


# ---- the clock: runs every few seconds on the server ----

def get_setting(db, key, default=None):
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(db, key, value):
    db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, str(value)))
    db.commit()


def owner_wrote(db):
    """Call on every message from the owner: WhatsApp's 24h window restarts now."""
    set_setting(db, "owner_last_msg", time.time())


def tick(db, send, now=None, clock=None):
    """Sends whatever is due. send(text) delivers to the owner. `now`/`clock` are injectable for tests."""
    now = now or local_now()
    clock = clock or time.time()
    last_msg = float(get_setting(db, "owner_last_msg", 0))
    tip = KEEP_ALIVE_TIP if clock - last_msg > 12 * 3600 else ""

    for e in upcoming(db):
        start = parse_time(e["start_at"])
        before_at = start - timedelta(minutes=e["remind_before_min"])
        if now >= start + timedelta(hours=2):                 # server was down: don't send stale alerts
            roll_or_close(db, e, start, "missed", now)
        elif now >= start:
            send(f"🔔 Now: {e['title']} ({start:%H:%M})" + tip)
            roll_or_close(db, e, start, "done", now)
        elif now >= before_at and not e["before_sent"] and e["remind_before_min"]:
            mins = int((start - now).total_seconds() // 60)
            send(f"⏰ In {mins} min: {e['title']} at {start:%H:%M}" + tip)
            db.execute("UPDATE events SET before_sent = 1 WHERE id = ?", (e["id"],))
            db.commit()

    today = now.strftime("%Y-%m-%d")
    summary_at = parse_time(f"{today} {config.MORNING_SUMMARY}") if config.MORNING_SUMMARY else None
    if summary_at and summary_at <= now < summary_at + timedelta(hours=2) \
            and get_setting(db, "summary_sent_for") != today:
        set_setting(db, "summary_sent_for", today)
        todays = [r for r in upcoming(db) if r["start_at"].startswith(today)]
        send("☀️ Good morning! Today:\n" + schedule_text(todays) + "\n\nReply 👍 to keep reminders on today.")

    if last_msg and clock - last_msg > config.KEEPALIVE_HOURS * 3600 \
            and get_setting(db, "keepalive_sent_for") != str(last_msg):
        set_setting(db, "keepalive_sent_for", last_msg)
        send("👋 Quick tap needed: reply anything (👍 is fine) so WhatsApp lets me keep sending your reminders.")


def roll_or_close(db, e, start, status, now):
    if e["repeat"]:
        nxt = next_occurrence(start, e["repeat"])
        while nxt <= now:
            nxt = next_occurrence(nxt, e["repeat"])
        db.execute("UPDATE events SET start_at = ?, before_sent = 0 WHERE id = ?", (nxt.strftime(FMT), e["id"]))
    else:
        db.execute("UPDATE events SET status = ? WHERE id = ?", (status, e["id"]))
    db.commit()
