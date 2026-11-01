# ONYX V5

Multi-server Discord bot built with Python, discord.py 2.x, and a database layer supporting PostgreSQL (recommended for hosted deployments) and SQLite (local development).

## Multi-server data separation
Server-specific tables use `guild_id` to scope moderation cases, warnings, leveling, role panels, settings, custom commands, embed templates, automod ignores, and `/shh` settings. Last.fm links are user-scoped.

## Included features
Retains the V4 cogs: moderation, automod, logging, utility, welcome/goodbye, roles, levels, custom commands/embeds, Last.fm, and restricted `/shh`. Adds `/setup`, `/settings`, and `/serverdata`.

## Local setup
1. Install Python 3.10+.
2. Copy `.env.example` to `.env` and set `DISCORD_TOKEN`.
3. Leave `DATABASE_URL` blank to use local SQLite.
4. Run `pip install -r requirements.txt`.
5. Run `python main.py`.

## Hosted setup (Render + PostgreSQL)
1. Create a PostgreSQL database with your hosting provider.
2. Add its private connection string as `DATABASE_URL` in the bot worker's environment.
3. Add `DISCORD_TOKEN` and `BOT_OWNER_ID`.
4. Set the worker start command to `python main.py`.
5. Deploy as a continuously running background worker.
6. Keep database credentials and bot token private.

The PostgreSQL schema initializes automatically on startup. SQLite is used when `DATABASE_URL` is not set.

## Important
- Never commit `.env`, bot tokens, or database credentials.
- This release initializes a fresh PostgreSQL schema; it does not automatically migrate existing V4 SQLite records.
- The `/serverdata` command shows counts for selected server-scoped tables; it does not delete data.
- Slash commands sync globally on startup, so new commands may take time to appear.
- Test permissions and role hierarchy in a private server before inviting ONYX broadly.


## Server-specific prefix

ONYX V5 defaults to the comma prefix `,`. Each server can configure its own prefix:

- `/prefix show` — show the current server prefix
- `/prefix set` — choose a prefix (1–5 characters, no spaces)
- `/prefix reset` — restore `,`

Members can use `,help` to see a note about ONYX's command interface. The existing feature commands are slash commands, so changing the text prefix does not convert those slash commands into text commands. The prefix setting is stored per server in `guild_settings`.
