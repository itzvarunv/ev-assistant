# EV Assistant

A personal WhatsApp assistant (official WhatsApp Cloud API) that remembers your schedule, reminds you,
and answers quick questions. It's a learning project, not a polished product. Read **Current status** first.

## Current status (honest version)

**What runs today:** a reminder bot on Meta's free **test number**, on an Oracle Cloud Always Free Micro VM,
with Google's **Gemini free API** as the AI. Only you (the owner) chat with it.

**What works:**
- Saves events from normal messages ("math test Saturday 10am", "class every weekday 8am") and confirms the exact date.
- Reminds you before (30 min default) and at the time, plus a 07:30 morning summary.
- Answers simple questions. Searches the web (DuckDuckGo) for news, prices, weather and similar.

**Limitations:**
- **It is not a fully capable AI.** Free models misread messages now and then, so always check the date in its ✅ confirmation.
- **Replies can be slow or fail.**
  - The free Gemini tier is sometimes overloaded. A reply can take from a few seconds to about a minute while EV falls back to another model.
  - If every model is busy, EV says so and you need to resend.
- **Web search is basic.** Free DuckDuckGo results can be thin or rate-limited, and the AI sometimes answers from memory instead of searching.
- **WhatsApp's 24 h rule:** EV can only message you within 24 h of your last message.
  - Reply 👍 once a day. EV nudges you after 20 h.
  - Reminders it couldn't deliver arrive late, marked as such.
- **Test number only:** it can message just the few numbers you register in Meta.
- **Not tested on real WhatsApp yet:**
  - answering *other people* on your own number (Coexistence)
  - the takeover/skip features
  - the dashboard
  - the Mac Reminders sync

  That needs a Meta-verified business or a paid partner.
- **Privacy:** with `LLM_PROVIDER=gemini`, your messages to EV are processed by Google (free tier data may be used to improve their models).

## Using it (messages from OWNER_PHONE)
- Write normally, e.g. "dentist tomorrow 5pm, remind me an hour before", or send a photo of a timetable.
- Commands: `today`, `tomorrow`, `week`, `cancel <id>`, `help`.

## Features in the code (built, mostly tested only locally)
- **Answering other people** on your number, with a 2 min reply delay so you can answer first.
- **Stepping aside:** if you reply yourself, EV stays quiet in that chat for 3 h.
- **Skip list** and **pause switch**.
- **Hand-offs:** requests that need you (money, meetings, favours) become tasks. EV asks for details once and never agrees on your behalf.
- **Profile:** `about_me.md` holds facts about you that EV may share. Copy `about_me.example.md`; the real file is git-ignored.
- **Documents:** files in `public/` can go to anyone. Files in `inbox/` stay private until you green-flag them.
- **Photos:** EV reads photos people send (bills, error screens) with a vision model.
- **Dashboard:** `https://<server>/dashboard`.
- **Mac Reminders sync:** `deploy/install_mac_sync.sh`.

## AI options (`LLM_PROVIDER` in `.env`)
- **`gemini`:** Google's free API. Works on a 1 GB server. `GEMINI_MODEL` takes a comma-separated list of fallbacks.
- **`ollama`:** local models, fully private.
  - Needs about 8 GB+ RAM on the server (e.g. Oracle Ampere A1, often out of capacity).
  - On an 8 GB laptop the 7B model is very slow.

## Try it locally
    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
    cp .env.example .env        # fill it in
    .venv/bin/python main.py    # C = chat as a contact, O = owner commands, I = ingest folders

## Deploy (Ubuntu server)
1. Copy the project: `rsync -av --exclude .venv --exclude data --exclude __pycache__ ./ ubuntu@SERVER_IP:ev/`
2. On the server: create `.env` from `.env.example`, then run `bash deploy/setup.sh`. It installs everything and prints the webhook URL.
3. In Meta: set that Callback URL with your `WA_VERIFY_TOKEN`, and subscribe to `messages`.
   - Link your WhatsApp Business Account to the app (`POST /{waba-id}/subscribed_apps`), or no messages arrive.
4. Use a permanent System User token (never expires) for `WA_TOKEN`. The "Try it out" token dies after 24 h.

Logs: `journalctl -u ev-assistant -f` · Restart: `sudo systemctl restart ev-assistant`

Secrets (`.env`), your profile (`about_me.md`), and chats/documents (`data/`, `inbox/`, `public/`) are git-ignored.
