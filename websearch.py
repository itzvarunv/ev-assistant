#Web search - lets EV look things up instead of bothering the owner
import requests
from bs4 import BeautifulSoup
import config
import learn

HEADERS = {"User-Agent": "Mozilla/5.0 (EV-assistant personal project)"}


def search(query, n=4):
    """Returns [{"title", "url", "snippet"}]. Free DuckDuckGo by default; Brave if you set a key."""
    if config.SEARCH_PROVIDER == "brave" and config.BRAVE_API_KEY:
        r = requests.get("https://api.search.brave.com/res/v1/web/search", timeout=20,
                         params={"q": query, "count": n},
                         headers={"X-Subscription-Token": config.BRAVE_API_KEY, "Accept": "application/json"})
        r.raise_for_status()
        return [{"title": x.get("title", ""), "url": x.get("url", ""), "snippet": x.get("description", "")}
                for x in r.json().get("web", {}).get("results", [])[:n]]
    from ddgs import DDGS
    return [{"title": x.get("title", ""), "url": x.get("href", ""), "snippet": x.get("body", "")}
            for x in DDGS().text(query, max_results=n)]


def page_text(url, limit=3000):
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()
    lines = [ln.strip() for ln in soup.get_text("\n").splitlines() if len(ln.strip()) > 40]
    return "\n".join(lines)[:limit]


def research(db, query):
    """Search, read the top page, keep it in the knowledge table for next time, and return a context block."""
    try:
        results = search(query)
    except Exception as e:
        print(f"[search] failed for {query!r}: {e}")
        return ""
    if not results:
        return ""
    block = "\n".join(f"- {r['title']}: {r['snippet']} ({r['url']})" for r in results)
    for r in results[:2]:
        try:
            text = page_text(r["url"])
        except Exception:
            continue
        if text:
            learn.store(db, query.lower(), r["url"], text)
            block += f"\n\nFrom {r['url']}:\n{text}"
            break
    return block
