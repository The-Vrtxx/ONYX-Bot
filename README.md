# ONYX V6 — Prefix Edition

ONYX is a modular Discord management bot for multiple servers. Each server has its own settings and text-command prefix.

## V6 command mode

ONYX V6 uses **prefix commands only**. The default prefix is `,`; server managers can change it with `,prefix set !`. Previously published global slash commands are cleared during startup.

Use `,help` to open the interactive category help menu. The help menu shows the server's current prefix.

## Features

- Moderation: ban, kick, timeout, warnings, purge, moderation cases, channel lock and slowmode
- AutoMod: invite/link/spam controls and ignored channels
- Logging: message, member and role event logs
- Welcome and goodbye messages
- Self-assignable roles and persistent role panels
- XP, ranks, leaderboards and level settings
- Custom text commands and saved embed templates
- Last.fm account linking and now-playing
- Server setup, settings and server data summaries
- Special `shh` role toggle with whitelist and owner-only configuration
- Per-server settings with PostgreSQL support; SQLite for local development

## Example commands

```text
,help
,ping
,ban @member reason
,timeout @member 10 reason
,warn @member reason
,rank
,leaderboard
,prefix show
,prefix set !
,shh @member
```

After changing the prefix, use the new prefix for all commands.

## Requirements

- Python 3.10+
- A Discord bot application
- PostgreSQL for hosted multi-server deployments (SQLite is supported locally)

## Setup

1. Install dependencies: `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in the values.
3. Enable **Server Members Intent** and **Message Content Intent** in the Discord Developer Portal.
4. Invite ONYX with the bot scope and required permissions.
5. Run locally with `python main.py`, or deploy as a persistent background worker.

## Environment variables

```env
DISCORD_TOKEN=your_bot_token
BOT_OWNER_ID=your_numeric_discord_user_id
DATABASE_PATH=data/bot.sqlite3
DATABASE_URL=
DEFAULT_PREFIX=,
LASTFM_API_KEY=
```

Keep your bot token and database credentials private. Never commit `.env`.

## Render deployment

- Runtime: Python
- Build command: `pip install -r requirements.txt`
- Start command: `python main.py`
- Set `DISCORD_TOKEN`, `BOT_OWNER_ID`, and `DATABASE_URL` in the worker's environment.
- Use the PostgreSQL service's **Internal Database URL** when the worker and database are in the same Render region.
- Use a paid persistent Background Worker for continuous operation; check current provider pricing before enabling paid services.

## Notes

- V6 keeps the existing V5 database schema and data model.
- The PostgreSQL adapter serializes access to its shared asyncpg connection.
- The first V6 startup clears previously published global slash commands. Discord may take a short time to refresh the command picker.
- Review the privacy policy and terms on your ONYX website so they accurately describe your actual data practices.
