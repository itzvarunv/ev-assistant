# EV Assistant

An AI assistant that answers WhatsApp messages on **your own number**, using the official WhatsApp Cloud API with Coexistence.
- It always introduces itself as "EV, <your name>'s AI assistant". It never confirms anything for you.
- It collects the details and turns anything that needs you into a task.

## Your personal assistant (messages from OWNER_PHONE)
- Write normally, e.g. "Math test Saturday 10am", "dentist tomorrow 5pm, remind me an hour before",
  "physics class every day at 8am", or send a photo of a timetable or notice.
- EV confirms the exact date back to you, so you can catch mistakes.
- Reminders arrive before the event (30 min by default) and again at the time.
- A morning summary arrives at `MORNING_SUMMARY` (default 07:30).
- Commands: `today`, `tomorrow`, `week`, `cancel <id>`, `help`. Ask questions any time.
- WhatsApp only lets EV message you within 24 h of your last message.
  - Reply 👍 once a day. EV nudges you after `KEEPALIVE_HOURS` (20 h) of silence.
  - Anything it couldn't deliver arrives when you next write, marked as late.

## Answering on its own (most messages)
- **about_me.md** (copy `about_me.example.md`; it's git-ignored): write what anyone may know about you (work, when you're free, your usual answers). This is the biggest quality win.
- **Web search**: for factual questions EV searches the web, answers from the results and saves them for next time.
  - Free DuckDuckGo by default.
  - Set `SEARCH_PROVIDER=brave` and `BRAVE_API_KEY` for more reliable results.
- **Photos**:
  - The vision model reads photos and stickers people send (bills, error screens, products).
  - It picks up text, amounts and dates.
  - EV answers from that, or makes a task for you.
  - Their photos are deleted once read.
  - Test it in `main.py` → C with `img /path/photo.jpg your caption`.
- **Region**: set `REGION` (e.g. `London, UK`) so answers use local prices, shops and rules.
- **Requests that need you** (money, meetings, favours):
  - EV asks for the missing details once.
  - The next message becomes a task for you.
  - EV never agrees on your behalf.

## How it behaves on your number
- **Reply delay:** EV waits `REPLY_DELAY_SECONDS` (default 2 min), so you get the first chance to answer.
- **You step in:** if you reply yourself from the WhatsApp Business app, EV stays quiet in that chat for `TAKEOVER_HOURS` (default 3 h).
- **Skip list:** people on it are never answered by EV.
- **Pause:** turn EV off for everyone from the dashboard.
- **Group chats and calls:** not supported by the API, so they stay yours.

## Where you see things
- **Dashboard:** `https://<server>/dashboard` (any username, your `DASHBOARD_PASSWORD`). It shows:
  - tasks, with "Send & close" and "Done"
  - who messaged and what they asked, with the full thread
  - the most-asked topics
  - the skip list
  - document upload and public/private switches
- **Reminders app:** run `bash deploy/install_mac_sync.sh` on your Mac once. New tasks are pulled into the "EV Assistant" list every 10 minutes while the Mac is on.

## Try it on your Mac (no WhatsApp needed)
    .venv/bin/python main.py          # C = chat as a contact, O = owner commands, I = ingest folders
Files in `public/` can go to anyone. Files in `inbox/` stay private until you make them public.

## Go live
1. Switch your number to the WhatsApp **Business** app (free; chats carry over). Use it normally for a while.
2. Get an always-on Ubuntu server, e.g. Oracle Cloud Always Free Ampere A1 (24 GB RAM, runs `qwen2.5:7b`).
3. Connect the number to the Cloud API with **Coexistence**:
   - Use a WhatsApp partner that supports it (e.g. 360dialog), or Meta's Embedded Signup as a Tech Provider.
   - Subscribe the webhook to `messages` and `smb_message_echoes`.
   - Contacts/history sync must be done within 24 h of onboarding.
4. Copy the project to the server:
   `rsync -av --exclude .venv --exclude data --exclude __pycache__ "EV assistant/" ubuntu@SERVER_IP:ev/`
5. On the server:
   - `cd ev && cp .env.example .env && nano .env` (leave `OWNER_PHONE` empty, set `DASHBOARD_PASSWORD`, `CHAT_MODEL=qwen2.5:7b`)
   - `bash deploy/setup.sh`
   - It prints the webhook URL. Paste it into Meta with your `WA_VERIFY_TOKEN`.
6. On your Mac:
   - Add `EV_SERVER_URL` and `DASHBOARD_PASSWORD` to `.env`.
   - Run `bash deploy/install_mac_sync.sh`.

Logs: `journalctl -u ev-assistant -f` · Restart: `sudo systemctl restart ev-assistant`
