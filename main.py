#EV Assistant - control panel
import sys
import config
import brain
import ingest
import learn
import owner
from db import get_connection


def list_docs(db):
    rows = db.execute("""
        SELECT d.doc_id, d.title, d.filename, GROUP_CONCAT(p.contact_id, ', ') AS shared
        FROM documents d LEFT JOIN doc_permissions p ON p.doc_id = d.doc_id
        GROUP BY d.doc_id ORDER BY d.doc_id
    """).fetchall()
    if not rows:
        print("No documents yet. Drop files into public/ (anyone) or inbox/ (private) and run Ingest.")
    for r in rows:
        print(f"[{r['doc_id']}] {r['title']} ({r['filename']})  green-flagged for: {r['shared'] or 'nobody'}")


def set_permission(db, grant):
    list_docs(db)
    doc_id = input("Document id: ").strip()
    who = input("Contact id (phone number), or * for everyone: ").strip()
    if not doc_id.isdigit() or not who:
        return
    if grant:
        db.execute("INSERT OR IGNORE INTO doc_permissions VALUES (?, ?)", (int(doc_id), who))
    else:
        db.execute("DELETE FROM doc_permissions WHERE doc_id = ? AND contact_id = ?", (int(doc_id), who))
    db.commit()
    print("Updated.")


def show_topics(db):
    for r in db.execute("SELECT topic, COUNT(*) AS n FROM questions GROUP BY topic ORDER BY n DESC LIMIT 20"):
        print(f"{r['n']:>4}  {r['topic']}")


def simulate_chat(db):
    """Test the bot in the terminal exactly as a WhatsApp contact would see it."""
    contact = input("Pretend contact id (e.g. +919999999999): ").strip() or "+000"
    name = input("Their name: ").strip() or "Friend"
    print("Type messages as them. To send a photo: img /path/to/photo.jpg optional caption. Empty line to stop.\n")
    while True:
        text = input(f"{name}: ").strip()
        if not text:
            break
        images = []
        if text.lower().startswith("img "):
            path, _, text = text[4:].strip().partition(" ")
            images = [path]
        out = brain.handle_message(db, contact, name, text, images)
        print(f"{config.ASSISTANT_NAME}: {out['reply']}")
        if out["file"]:
            print(f"   [sends file: {out['file']}]")
        if out["task_id"]:
            print(f"   [task #{out['task_id']} created for {config.OWNER_NAME}]")


def owner_mode(db):
    """Try the commands you'll send EV from your own WhatsApp."""
    print("Type commands as the owner (try: tasks, reply 1 Sure!, docs). Empty line to stop.\n")
    while True:
        text = input("You: ").strip()
        if not text:
            break
        print(owner.handle_command(db, text, lambda to, body: print(f"   [sends to {to}: {body}]")))


def main():
    db = get_connection()
    print("----------------------------------")
    print(f"        {config.ASSISTANT_NAME} ASSISTANT")
    print(f"   Speaks for {config.OWNER_NAME} on WhatsApp")
    print("----------------------------------")
    while True:
        print("\n[C]hat test   [O]wner mode     [I]ngest folders   [D]ocuments")
        print("[G]reen-flag  [R]evoke         [T]opics   [L]earn   [Q]uit")
        choice = input("\n> ").strip().lower()
        if choice == "c":
            simulate_chat(db)
        elif choice == "o":
            owner_mode(db)
        elif choice == "i":
            ingest.ingest_all(db)
        elif choice == "d":
            list_docs(db)
        elif choice == "g":
            set_permission(db, grant=True)
        elif choice == "r":
            set_permission(db, grant=False)
        elif choice == "t":
            show_topics(db)
        elif choice == "l":
            learn.learn(db)
        elif choice == "q":
            sys.exit()


if __name__ == "__main__":
    main()
