#WhatsApp Cloud API (official) - send text/files, download media, verify webhook signatures
import hashlib
import hmac
import mimetypes
import re
from pathlib import Path
import requests
import config

API = f"https://graph.facebook.com/{config.GRAPH_VERSION}"


class WhatsAppError(Exception):
    pass


def _headers():
    return {"Authorization": f"Bearer {config.WA_TOKEN}"}


def _send(payload):
    payload = {"messaging_product": "whatsapp", **payload}
    r = requests.post(f"{API}/{config.WA_PHONE_NUMBER_ID}/messages", headers=_headers(), json=payload, timeout=30)
    if not r.ok:
        raise WhatsAppError(r.text)


def send_text(to, body):
    _send({"to": to, "type": "text", "text": {"body": body[:4096]}})


def send_document(to, path, caption=""):
    path = Path(path)
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    with open(path, "rb") as f:
        r = requests.post(f"{API}/{config.WA_PHONE_NUMBER_ID}/media", headers=_headers(), timeout=120,
                          data={"messaging_product": "whatsapp", "type": mime},
                          files={"file": (path.name, f, mime)})
    if not r.ok:
        raise WhatsAppError(r.text)
    _send({"to": to, "type": "document",
           "document": {"id": r.json()["id"], "filename": path.name, "caption": caption}})


def download_media(media_id, folder, filename=None):
    meta = requests.get(f"{API}/{media_id}", headers=_headers(), timeout=30)
    if not meta.ok:
        raise WhatsAppError(meta.text)
    meta = meta.json()
    ext = mimetypes.guess_extension(meta.get("mime_type", "").split(";")[0]) or ""
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(filename).name) if filename else f"{media_id}{ext}"
    data = requests.get(meta["url"], headers=_headers(), timeout=120)
    if not data.ok:
        raise WhatsAppError(data.text)
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_bytes(data.content)
    return path


def valid_signature(body, header):
    """Meta signs every webhook with your App Secret; reject anything else."""
    expected = "sha256=" + hmac.new(config.WA_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header or "")
