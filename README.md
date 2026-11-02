# ONYX

ONYX is a multi-server Discord management bot built to keep server administration, moderation, and community tools organized in one place.

All bot commands use a message prefix. ONYX does not use slash commands.

Getting Started

Requirements

* Python 3.10 or newer
* A Discord bot application
* Message Content Intent enabled
* Server Members Intent enabled
* PostgreSQL for hosted deployments, or SQLite for local development

Install

1. Install the dependencies:
    pip install -r requirements.txt
2. Copy .env.example to .env.
3. Add your bot configuration to .env.
4. Start the bot:
    python main.py

Configuration

Set these environment variables:

Variable	Purpose
DISCORD_TOKEN	Discord bot token
BOT_OWNER_ID	Numeric Discord user ID for the bot owner
DATABASE_URL	PostgreSQL connection string; omit for local SQLite

Never commit your bot token, database credentials, or other secrets to GitHub.

Commands

The default prefix is ,.

* ,help — Open the interactive command guide.
* ,prefix show — Show this server’s current prefix.
* ,prefix set ! — Change the server prefix (Manage Server).
* ,prefix reset — Restore the default prefix (Manage Server).

Use the configured prefix with all commands. For example: ,ban, ,rank, ,setup, ,lastfm link, and ,shh.

The help command lists commands available from the cogs that successfully load.

Hosting

For Render, create a Background Worker.

* Build command: pip install -r requirements.txt
* Start command: python main.py

Add the required environment variables in the Render service settings. Keep secrets in the service environment, not in the repository.

Discord Intents

Enable the following intents in the Discord Developer Portal:

* Message Content Intent
* Server Members Intent

The bot also uses guild and voice-state events for its server and voice features.

Updates

This section records user-facing changes added to ONYX. New updates will be appended here as features are introduced.

VoiceMaster Control Panel

* Added a setup flow for creating the VoiceMaster category, join-to-create channel, and control-panel channel.
* Added interactive controls for room privacy, visibility, ownership, member disconnects, channel information, and user limits.
* The interface is designed to remain interactive after bot restarts.

SHH Command Behavior

* Successful ,shh use applies or removes the configured role, reacts to the command message with 🤫, and deletes that command message after five seconds.
* Successful use does not send a separate confirmation message.

Roles and Command Help

* Expanded role-management functionality with role creation and deletion, auto roles, and reaction roles.
* Updated the help system to build its command index from loaded commands so new commands can appear automatically.

### Anti-Nuke Protection

- Added configurable threshold-based anti-nuke detection.
- Added ban, kick, jail, and staff-role stripping punishments.
- Added trusted-user whitelist management.
- Added configurable jail and staff roles.
- Added security event logging and protection status commands.

Reporting Issues

When reporting a problem, include the command used, the error message, and relevant Render log output. Remove tokens, passwords, database URLs, and other private values before sharing logs.
