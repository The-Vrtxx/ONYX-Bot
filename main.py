import os
import logging
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

from database import Database

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")

TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0") or 0)
DB_PATH = os.getenv("DATABASE_PATH", "data/bot.sqlite3")
DATABASE_URL = os.getenv("DATABASE_URL")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True
intents.moderation = True

class CommunityBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.db = Database(DB_PATH, DATABASE_URL)
        self.owner_id = OWNER_ID
        self.started_at = discord.utils.utcnow()

    async def setup_hook(self):
        await self.db.connect()
        await self.db.initialize()
        for path in sorted(Path("cogs").glob("*.py")):
            if path.name.startswith("_"):
                continue
            await self.load_extension(f"cogs.{path.stem}")
            log.info("Loaded %s", path.stem)
        # Global sync publishes slash commands. For development, use a test guild
        # sync to avoid waiting for global command propagation.
        await self.tree.sync()
        log.info("Slash commands synced. Database backend: %s", self.db.backend)

    async def close(self):
        await self.db.close()
        await super().close()

bot = CommunityBot()

@bot.event
async def on_ready():
    log.info("Logged in as %s (%s)", bot.user, bot.user.id)
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name="/help • your server"
    ))

@bot.tree.command(name="help", description="Browse the bot's command categories.")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Bot command guide",
        description="Use Discord's `/` command picker to discover commands.",
        color=discord.Color.blurple()
    )
    categories = {
        "Moderation": "/ban, /kick, /timeout, /untimeout, /warn, /warnings, /purge, /modlogs, /case, /warn_escalation, /lock, /unlock, /slowmode",
        "Automod": "/automod settings",
        "Logging": "/logging set",
        "Utility": "/ping, /userinfo, /serverinfo, /avatar, /botinfo",
        "Welcome": "/welcome set",
        "Roles": "/selfrole_add, /selfrole_remove, /selfrole_list, /role, /rolepanel_create",
        "Levels": "/rank, /leaderboard, /levels settings",
        "Custom": "/embed, /custom add, /custom run",
        "Last.fm": "/lastfm link, /lastfm nowplaying",
        "Special": "/shh, /shh_whitelist_add, /shh_whitelist_remove, /shh_set_role"
    }
    for name, value in categories.items():
        embed.add_field(name=name, value=value, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: Exception):
    if isinstance(error, commands.MissingPermissions):
        message = "You don't have permission to use that command."
    elif isinstance(error, commands.BotMissingPermissions):
        message = "I don't have the Discord permissions needed for that."
    elif isinstance(error, commands.CommandOnCooldown):
        message = f"Slow down! Try again in {error.retry_after:.1f} seconds."
    elif isinstance(error, commands.CheckFailure):
        message = "You can't use that command here or with your current permissions."
    else:
        log.error("Slash command error", exc_info=error)
        message = "Something went wrong while running that command."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing. Copy .env.example to .env and add your bot token.")

bot.run(TOKEN)
