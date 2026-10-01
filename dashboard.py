#Dashboard - private web page: who messaged, what they asked, your tasks and EV's controls
import hashlib
import hmac
import threading
from functools import wraps
from flask import Blueprint, Response, abort, jsonify, redirect, render_template_string, request, url_for
from werkzeug.utils import secure_filename
import config
import ingest
import owner
import whatsapp
from db import ev_is_on, get_connection

bp = Blueprint("dashboard", __name__)


def csrf_token():
    return hmac.new(config.DASHBOARD_PASSWORD.encode(), b"ev-dashboard-form", hashlib.sha256).hexdigest()


def protected(view):
    """HTTP basic auth (user: anything, password: DASHBOARD_PASSWORD) + a form token on every POST."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not config.DASHBOARD_PASSWORD:
            abort(404)
        auth = request.authorization
        if not auth or not hmac.compare_digest(auth.password or "", config.DASHBOARD_PASSWORD):
            return Response("Login required", 401, {"WWW-Authenticate": 'Basic realm="EV"'})
        if request.method == "POST" and not hmac.compare_digest(request.form.get("csrf", ""), csrf_token()):
            abort(403)
        return view(*args, **kwargs)
    return wrapper


def run_command(text):
    db = get_connection()
    try:
        msg = owner.handle_command(db, text, whatsapp.send_text)
    except whatsapp.WhatsAppError as e:
        msg = f"WhatsApp refused it (they may not have messaged in the last 24 h): {e}"
    return redirect(url_for("dashboard.home", msg=msg))


@bp.get("/dashboard")
@protected
def home():
    db = get_connection()
    open_tasks = db.execute("SELECT * FROM tasks WHERE status = 'open' ORDER BY id DESC").fetchall()
    chats = db.execute("""
        SELECT c.contact_id, c.name, MAX(m.at) AS last_at,
               (SELECT text FROM messages WHERE contact_id = c.contact_id AND role = 'user'
                ORDER BY id DESC LIMIT 1) AS last_ask
        FROM contacts c JOIN messages m ON m.contact_id = c.contact_id
        GROUP BY c.contact_id ORDER BY last_at DESC LIMIT 40""").fetchall()
    threads = {c["contact_id"]: list(reversed(db.execute(
        "SELECT role, text, at FROM messages WHERE contact_id = ? ORDER BY id DESC LIMIT 20",
        (c["contact_id"],)).fetchall())) for c in chats}
    topics = db.execute("""SELECT topic, COUNT(*) AS n FROM questions WHERE at >= datetime('now', '-30 days')
                           GROUP BY topic ORDER BY n DESC LIMIT 10""").fetchall()
    docs = db.execute("""
        SELECT d.doc_id, d.title, d.filename,
               EXISTS(SELECT 1 FROM doc_permissions p WHERE p.doc_id = d.doc_id AND p.contact_id = '*') AS public
        FROM documents d ORDER BY d.doc_id DESC""").fetchall()
    skipped = db.execute("SELECT contact_id FROM skip_contacts ORDER BY contact_id").fetchall()
    return render_template_string(PAGE, tasks=open_tasks, chats=chats, threads=threads, topics=topics,
                                  docs=docs, skipped=skipped, ev_on=ev_is_on(db), csrf=csrf_token(),
                                  msg=request.args.get("msg"), cfg=config)


@bp.post("/dashboard/task/<int:task_id>/reply")
@protected
def reply_task(task_id):
    return run_command(f"reply {task_id} {request.form.get('text', '').strip()}")


@bp.post("/dashboard/task/<int:task_id>/done")
@protected
def done_task(task_id):
    return run_command(f"done {task_id}")


@bp.post("/dashboard/power")
@protected
def power():
    return run_command("on" if request.form.get("state") == "on" else "off")


@bp.post("/dashboard/skip")
@protected
def skip():
    action = "unskip" if request.form.get("action") == "remove" else "skip"
    return run_command(f"{action} {request.form.get('phone', '')}")


@bp.post("/dashboard/doc/<int:doc_id>/visibility")
@protected
def visibility(doc_id):
    return run_command(f"{'share' if request.form.get('public') == '1' else 'unshare'} {doc_id} *")


@bp.post("/dashboard/upload")
@protected
def upload():
    f = request.files.get("file")
    name = secure_filename(f.filename) if f and f.filename else ""
    if not name:
        return redirect(url_for("dashboard.home", msg="Choose a file first."))
    public = request.form.get("public") == "1"
    folder = config.PUBLIC_DIR if public else config.INBOX
    folder.mkdir(exist_ok=True)
    path = folder / name
    f.save(path)
    # Reading a scan with the vision model can take minutes, so do it in the background.
    threading.Thread(target=lambda: ingest.ingest_file(get_connection(), path, public), daemon=True).start()
    return redirect(url_for("dashboard.home", msg=f"Uploaded {name} - it will appear under Documents once read."))


@bp.get("/api/tasks")
@protected
def api_tasks():
    """Feed for sync_reminders.py on your Mac: tasks newer than ?after=<id>."""
    after = request.args.get("after", 0, type=int)
    rows = get_connection().execute(
        "SELECT id, contact_name, contact_id, title, details, due FROM tasks WHERE id > ? ORDER BY id",
        (after,)).fetchall()
    return jsonify([dict(r) for r in rows])


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>EV Dashboard</title>
<style>
:root { --bg:#f6f7f9; --card:#fff; --text:#1c1f23; --muted:#667085; --line:#e4e7ec; --accent:#128c7e; --warn:#b42318; }
@media (prefers-color-scheme: dark) { :root { --bg:#111418; --card:#1a1f25; --text:#e8eaed; --muted:#98a2b3; --line:#2b323b; --accent:#25d3a6; --warn:#f97066; } }
* { box-sizing:border-box; } body { margin:0; background:var(--bg); color:var(--text); font:15px/1.45 system-ui, sans-serif; }
main { max-width:980px; margin:0 auto; padding:16px; }
header { display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; margin-bottom:12px; }
h1 { font-size:22px; margin:0; } h2 { font-size:16px; margin:0 0 10px; }
section { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px; margin-bottom:14px; }
.muted { color:var(--muted); font-size:13px; } .pill { font-size:12px; padding:2px 8px; border-radius:99px; border:1px solid var(--line); }
.on { color:var(--accent); border-color:var(--accent); } .off { color:var(--warn); border-color:var(--warn); }
.item { border-top:1px solid var(--line); padding:10px 0; } .item:first-of-type { border-top:0; }
form.inline { display:inline; } .row { display:flex; gap:8px; flex-wrap:wrap; margin-top:6px; }
input[type=text], textarea { flex:1; min-width:0; padding:8px; border-radius:8px; border:1px solid var(--line); background:var(--bg); color:var(--text); font:inherit; }
button { padding:7px 12px; border-radius:8px; border:1px solid var(--line); background:var(--bg); color:var(--text); cursor:pointer; font:inherit; }
button.primary { background:var(--accent); border-color:var(--accent); color:#fff; }
.msg { background:var(--card); border-left:3px solid var(--accent); padding:8px 12px; border-radius:8px; margin-bottom:12px; }
.bubble { padding:6px 10px; border-radius:10px; margin:4px 0; max-width:85%; white-space:pre-wrap; word-wrap:break-word; }
.user { background:var(--bg); } .assistant { background:color-mix(in srgb, var(--accent) 14%, transparent); margin-left:auto; }
.thread { display:flex; flex-direction:column; } summary { cursor:pointer; } .grid { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
@media (max-width:720px) { .grid { grid-template-columns:1fr; } }
</style></head><body><main>
<header>
  <h1>EV Dashboard</h1>
  <form class="inline" method="post" action="{{ url_for('dashboard.power') }}">
    <input type="hidden" name="csrf" value="{{ csrf }}">
    {% if ev_on %}<span class="pill on">EV is answering</span> <button name="state" value="off">Pause EV</button>
    {% else %}<span class="pill off">EV is paused</span> <button class="primary" name="state" value="on">Resume EV</button>{% endif %}
  </form>
</header>
{% if msg %}<div class="msg">{{ msg }}</div>{% endif %}

<section><h2>Needs your decision ({{ tasks|length }})</h2>
{% for t in tasks %}<div class="item">
  <b>#{{ t.id }} {{ t.contact_name }}</b> <span class="muted">{{ t.contact_id }} · {{ t.created }}{% if t.due %} · due {{ t.due }}{% endif %}</span>
  <div>{{ t.title }}</div><div class="muted">{{ t.details }}</div>
  <div class="row">
    <form class="row" style="flex:1;margin:0" method="post" action="{{ url_for('dashboard.reply_task', task_id=t.id) }}">
      <input type="hidden" name="csrf" value="{{ csrf }}">
      <input type="text" name="text" placeholder="Your answer - sent as 'Message from {{ cfg.OWNER_NAME }}'" required>
      <button class="primary">Send &amp; close</button>
    </form>
    <form class="inline" method="post" action="{{ url_for('dashboard.done_task', task_id=t.id) }}">
      <input type="hidden" name="csrf" value="{{ csrf }}"><button>Done</button></form>
  </div>
</div>{% else %}<div class="muted">Nothing waiting on you 🎉</div>{% endfor %}
</section>

<section><h2>Who messaged</h2>
{% for c in chats %}<details class="item"><summary>
  <b>{{ c.name or c.contact_id }}</b> <span class="muted">{{ c.contact_id }} · {{ c.last_at }}</span>
  <div class="muted">asked: {{ (c.last_ask or '')[:140] }}</div></summary>
  <div class="thread">{% for m in threads[c.contact_id] %}<div class="bubble {{ m.role }}">{{ m.text }}</div>{% endfor %}</div>
</details>{% else %}<div class="muted">No conversations yet.</div>{% endfor %}
</section>

<div class="grid">
<section><h2>Most asked (30 days)</h2>
{% for t in topics %}<div class="item">{{ t.topic }} <span class="muted">× {{ t.n }}</span></div>{% else %}<div class="muted">No questions yet.</div>{% endfor %}
</section>

<section><h2>Skip list</h2><div class="muted">EV never answers these numbers.</div>
{% for s in skipped %}<form class="item row" method="post" action="{{ url_for('dashboard.skip') }}">
  <input type="hidden" name="csrf" value="{{ csrf }}"><input type="hidden" name="phone" value="{{ s.contact_id }}">
  <span style="flex:1">{{ s.contact_id }}</span><button name="action" value="remove">Remove</button></form>{% endfor %}
<form class="row" method="post" action="{{ url_for('dashboard.skip') }}">
  <input type="hidden" name="csrf" value="{{ csrf }}">
  <input type="text" name="phone" placeholder="+91 98765 43210" required><button name="action" value="add">Add</button>
</form>
</section>
</div>

<section><h2>Documents</h2>
<form class="row" method="post" enctype="multipart/form-data" action="{{ url_for('dashboard.upload') }}">
  <input type="hidden" name="csrf" value="{{ csrf }}">
  <input type="file" name="file" required>
  <label><input type="checkbox" name="public" value="1" checked> Anyone can get it</label>
  <button class="primary">Upload</button>
</form>
{% for d in docs %}<form class="item row" method="post" action="{{ url_for('dashboard.visibility', doc_id=d.doc_id) }}">
  <input type="hidden" name="csrf" value="{{ csrf }}">
  <span style="flex:1">[{{ d.doc_id }}] {{ d.title }} <span class="muted">{{ d.filename }}</span></span>
  {% if d.public %}<span class="pill on">public</span><button name="public" value="0">Make private</button>
  {% else %}<span class="pill">private</span><button name="public" value="1">Make public</button>{% endif %}
</form>{% else %}<div class="muted">No documents yet.</div>{% endfor %}
</section>
</main></body></html>"""
