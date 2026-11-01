# ONYX V6 — Prefix Edition

ONYX is a multi-server Discord management bot. **Every bot command is a native message-prefix command. There are no slash commands or application-command registrations in this edition.**

## Requirements
- Python 3.10+
- Discord bot with Message Content Intent and Server Members Intent enabled
- PostgreSQL (recommended for Render) or SQLite for local development

## Setup
1. Install dependencies: `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in your values.
3. Run `python main.py`.

## Prefix
Default prefix: `,`
- `,help` — interactive command guide
- `,prefix show` — view this server's prefix
- `,prefix set !` — change prefix (Manage Server)
- `,prefix reset` — reset to comma (Manage Server)

All commands use the configured prefix, e.g. `,ban`, `,rank`, `,setup`, `,lastfm link`, and `,shh`.

## Hosting
For Render, run this as a Background Worker with build command `pip install -r requirements.txt` and start command `python main.py`. Set `DISCORD_TOKEN`, `BOT_OWNER_ID`, and `DATABASE_URL` in the service environment. Keep secrets out of Git.

## Intents
Enable **Message Content Intent** and **Server Members Intent** in the Discord Developer Portal.
