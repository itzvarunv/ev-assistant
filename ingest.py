#Ingest - reads every new file in public/ and inbox/ once and stores it in SQL
import hashlib
import threading
import json
import pymupdf as fitz
import config
import llm

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
TEXT_EXT = {".txt", ".md", ".csv"}
LOCK = threading.Lock()   # the folder watcher and WhatsApp uploads may ingest at the same time

VISION_PROMPT = ("This is a scanned document or photo. Transcribe all readable text exactly. "
                 "If there is little text, describe what the image shows.")

SUMMARY_PROMPT = """Here is the content of a file named "{name}". Answer ONLY with JSON:
{{"title": "short human title", "description": "one sentence on what this document is"}}

CONTENT:
{content}"""


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(path):
    ext = path.suffix.lower()
    if ext in IMAGE_EXT:
        return "image", llm.look_at(path.read_bytes(), VISION_PROMPT)
    if ext in TEXT_EXT:
        return "text", path.read_text(errors="ignore")
    if ext == ".pdf":
        pdf = fitz.open(path)
        text = "\n".join(page.get_text() for page in pdf)
        if len(text.strip()) > 50:
            return "pdf", text
        # Scanned PDF: render the first pages and let the vision model read them.
        pages = [llm.look_at(page.get_pixmap(dpi=150).tobytes("png"), VISION_PROMPT)
                 for page in list(pdf)[:3]]
        return "pdf-scan", "\n\n".join(pages)
    return None, None


def summarize(name, content):
    try:
        out = json.loads(llm.chat([{"role": "user", "content": SUMMARY_PROMPT.format(
            name=name, content=content[:3000])}], json_mode=True))
        return str(out.get("title") or name), str(out.get("description") or "")
    except (json.JSONDecodeError, ValueError):
        return name, ""


def ingest_file(db, path, public):
    """Reads one file into SQL. public=True means anyone may receive it. Returns (doc_id, title) or None."""
    with LOCK:
        digest = sha256(path)
        row = db.execute("SELECT doc_id, title FROM documents WHERE sha256 = ?", (digest,)).fetchone()
        if row:
            doc_id, title = row["doc_id"], row["title"]
        else:
            print(f"Reading {path.name} ...")
            kind, content = extract(path)
            if kind is None:
                print(f"  skipped (unsupported type {path.suffix})")
                return None
            title, description = summarize(path.name, content)
            cur = db.execute(
                "INSERT INTO documents (path, filename, sha256, kind, title, description, content) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(path), path.name, digest, kind, title, description, content))
            doc_id = cur.lastrowid
            db.execute("INSERT INTO documents_fts (rowid, title, description, content) VALUES (?, ?, ?, ?)",
                       (doc_id, title, description, content))
            print(f"  [{doc_id}] {title} - {'shared with everyone' if public else 'private until you green-flag it'}")
        if public:
            db.execute("UPDATE documents SET path = ? WHERE doc_id = ?", (str(path), doc_id))
            db.execute("INSERT OR IGNORE INTO doc_permissions VALUES (?, '*')", (doc_id,))
        db.commit()
        return doc_id, title


def ingest_all(db):
    """public/ = anyone can get it, inbox/ = private. Already-read files are skipped (by content hash)."""
    for folder, public in ((config.PUBLIC_DIR, True), (config.INBOX, False)):
        folder.mkdir(exist_ok=True)
        for path in sorted(folder.rglob("*")):
            if path.is_file() and not path.name.startswith("."):
                ingest_file(db, path, public)
