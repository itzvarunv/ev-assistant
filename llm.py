#LLM - local via Ollama, or Google Gemini's free API for small servers (LLM_PROVIDER in .env)
import base64
import requests
import config

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def chat(messages, json_mode=False, model=None):
    if config.LLM_PROVIDER == "gemini":
        return _gemini(messages, json_mode)
    body = {
        "model": model or config.CHAT_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.4},
    }
    if json_mode:
        body["format"] = "json"
    r = requests.post(f"{config.OLLAMA_URL}/api/chat", json=body, timeout=600)
    r.raise_for_status()
    return r.json()["message"]["content"]


def look_at(image_bytes, prompt):
    msg = {"role": "user", "content": prompt,
           "images": [base64.b64encode(image_bytes).decode()]}
    return chat([msg], model=config.VISION_MODEL)


def _mime(b64):
    head = base64.b64decode(b64[:16])
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head[:4] == b"RIFF":
        return "image/webp"
    return "image/jpeg"


def _gemini(messages, json_mode):
    """Same message format as Ollama, translated to Gemini's: system -> systemInstruction, assistant -> model."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    contents = []
    for m in messages:
        if m["role"] == "system":
            continue
        role = "model" if m["role"] == "assistant" else "user"
        parts = [{"text": m["content"]}] + [{"inline_data": {"mime_type": _mime(img), "data": img}}
                                            for img in m.get("images", [])]
        if contents and contents[-1]["role"] == role:     # Gemini wants turns to alternate
            contents[-1]["parts"] += parts
        else:
            contents.append({"role": role, "parts": parts})
    body = {"contents": contents, "generationConfig": {"temperature": 0.4}}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    # GEMINI_MODEL can list backups ("a,b,c"): a busy or retired model falls through to the next one.
    for model in [m.strip() for m in config.GEMINI_MODEL.split(",") if m.strip()]:
        r = requests.post(GEMINI_URL.format(model=model), json=body, timeout=120,
                          headers={"x-goog-api-key": config.GEMINI_API_KEY})   # header, so the key never sits in URLs/logs
        if r.status_code not in (404, 429, 500, 502, 503, 504):
            break
    r.raise_for_status()
    candidates = r.json().get("candidates") or [{}]
    return "".join(p.get("text", "") for p in candidates[0].get("content", {}).get("parts", []))
