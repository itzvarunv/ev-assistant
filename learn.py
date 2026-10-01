#Learn - researches what people ask about most and stores it for retrieval (RAG, not weight training)
import requests
from bs4 import BeautifulSoup
import config

HEADERS = {"User-Agent": "EV-assistant/0.1 (personal project)"}
WIKI_API = "https://en.wikipedia.org/w/api.php"
SOURCES_FILE = config.BASE / "sources.txt"   # optional lines: topic | https://url


def frequent_topics(db):
    return db.execute("""
        SELECT topic, COUNT(*) AS asks FROM questions
        WHERE at >= datetime('now', '-30 days')
        GROUP BY topic HAVING asks >= ? ORDER BY asks DESC LIMIT 10
    """, (config.LEARN_MIN_ASKS,)).fetchall()


def chunks(text, size=800):
    paras = [p.strip() for p in text.split("\n") if len(p.strip()) > 40]
    buf = ""
    for p in paras:
        if len(buf) + len(p) > size and buf:
            yield buf
            buf = ""
        buf += p + "\n"
    if buf:
        yield buf


def wikipedia(topic, pages=2):
    found = requests.get(WIKI_API, headers=HEADERS, timeout=20, params={
        "action": "query", "list": "search", "srsearch": topic, "srlimit": pages, "format": "json"}).json()
    for hit in found.get("query", {}).get("search", []):
        page = requests.get(WIKI_API, headers=HEADERS, timeout=20, params={
            "action": "query", "prop": "extracts", "explaintext": 1, "titles": hit["title"],
            "format": "json"}).json()
        for p in page["query"]["pages"].values():
            yield f"wikipedia:{hit['title']}", p.get("extract", "")[:20000]


def web_page(url):
    html = requests.get(url, headers=HEADERS, timeout=20).text
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return soup.get_text("\n")[:20000]


def user_sources():
    if not SOURCES_FILE.exists():
        return []
    rows = []
    for line in SOURCES_FILE.read_text().splitlines():
        if "|" in line and not line.startswith("#"):
            topic, url = (s.strip() for s in line.split("|", 1))
            rows.append((topic.lower(), url))
    return rows


def store(db, topic, source, text):
    if db.execute("SELECT 1 FROM knowledge WHERE source = ?", (source,)).fetchone():
        return 0
    n = 0
    for c in chunks(text):
        cur = db.execute("INSERT INTO knowledge (topic, source, chunk) VALUES (?, ?, ?)", (topic, source, c))
        db.execute("INSERT INTO knowledge_fts (rowid, topic, chunk) VALUES (?, ?, ?)", (cur.lastrowid, topic, c))
        n += 1
    db.commit()
    return n


def learn(db):
    topics = frequent_topics(db)
    if not topics:
        print(f"No topic has been asked {config.LEARN_MIN_ASKS}+ times in the last 30 days yet.")
    for t in topics:
        print(f"Researching '{t['topic']}' (asked {t['asks']}x)")
        try:
            for source, text in wikipedia(t["topic"]):
                print(f"  {source}: {store(db, t['topic'], source, text)} chunks")
        except requests.RequestException as e:
            print(f"  wikipedia failed: {e}")
    for topic, url in user_sources():
        try:
            print(f"  {url}: {store(db, topic, url, web_page(url))} chunks")
        except requests.RequestException as e:
            print(f"  {url} failed: {e}")
