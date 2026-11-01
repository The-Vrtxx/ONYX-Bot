import os
import logging
import inspect
import shlex
from pathlib import Path
from typing import get_origin, get_args, Union
import types

import discord
from discord.ext import commands
from discord import app_commands
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

async def get_prefix(bot, message):
    # Each server gets its own prefix; DMs fall back to the default.
    prefix = ","
    if message.guild is not None and getattr(bot, "db", None) is not None:
        try:
            row = await bot.db.fetchone(
                "SELECT prefix FROM guild_settings WHERE guild_id=?",
                (message.guild.id,)
            )
            if row and row["prefix"]:
                prefix = row["prefix"]
        except Exception:
            log.exception("Could not load prefix for guild %s; using default", message.guild.id)
    return commands.when_mentioned_or(prefix)(bot, message)


class _PrefixResponse:
    def __init__(self, ctx):
        self.ctx = ctx
        self._done = False

    async def send_message(self, content=None, *, embed=None, embeds=None, **kwargs):
        self._done = True
        await self.ctx.send(content=content, embed=embed, embeds=embeds, allowed_mentions=kwargs.get("allowed_mentions"))

    async def defer(self, **kwargs):
        self._done = True

    def is_done(self):
        return self._done


class _PrefixInteraction:
    """Small adapter allowing existing interaction callbacks to run from prefix commands."""
    def __init__(self, ctx):
        self._ctx = ctx
        self.user = ctx.author
        self.guild = ctx.guild
        self.channel = ctx.channel
        self.client = ctx.bot
        self.response = _PrefixResponse(ctx)
        self.followup = self.response
        self.permissions = getattr(ctx.author, "guild_permissions", discord.Permissions.none())
        me = ctx.guild.me if ctx.guild else None
        self.app_permissions = getattr(me, "guild_permissions", discord.Permissions.none())


async def _convert_prefix_argument(ctx, annotation, token, parameter):
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in (Union, types.UnionType) and type(None) in args:
        annotation = next((a for a in args if a is not type(None)), str)
    # app_commands.Choice[T] is represented as the underlying value for text commands.
    if getattr(annotation, "__name__", "") == "Choice" or getattr(origin, "__name__", "") == "Choice":
        annotation = str
    if annotation is inspect.Parameter.empty or annotation is str:
        return token
    if annotation is bool:
        lowered = token.lower()
        if lowered in ("true", "yes", "on", "1", "enable", "enabled"):
            return True
        if lowered in ("false", "no", "off", "0", "disable", "disabled"):
            return False
        raise commands.BadArgument(f"'{token}' isn't a boolean. Use true or false.")
    if annotation is int:
        try:
            return int(token)
        except ValueError as exc:
            raise commands.BadArgument(f"'{token}' must be a whole number.") from exc
    return await commands.run_converters(ctx, annotation, token, parameter)


def _register_prefix_app_command(bot, app_command, prefix_name=None):
    """Expose every existing app-command callback as a prefix command too."""
    if isinstance(app_command, app_commands.Group):
        group_name = prefix_name or app_command.name
        async def group_callback(ctx):
            await ctx.send(f"Use `{ctx.prefix}{group_name} <subcommand>`. Try `{ctx.prefix}help` for examples.")
        group = commands.Group(name=group_name, callback=group_callback, invoke_without_command=True)
        for child in app_command.commands:
            if isinstance(child, app_commands.Group):
                nested = _register_prefix_app_command(bot, child)
                group.add_command(nested)
            else:
                group.add_command(_make_prefix_leaf(child))
        return group
    return _make_prefix_leaf(app_command, prefix_name)


def _make_prefix_leaf(app_command, prefix_name=None):
    name = prefix_name or app_command.name
    callback = app_command.callback
    binding = getattr(app_command, "binding", None)
    params = list(getattr(app_command, "parameters", []))

    async def invoke(ctx, *, raw=""):
        if ctx.guild is None:
            return await ctx.send("This command can only be used inside a server.")
        interaction = _PrefixInteraction(ctx)
        # Re-run the original application-command permission/check predicates.
        for predicate in getattr(app_command, "checks", []):
            passed = predicate(interaction)
            if inspect.isawaitable(passed):
                passed = await passed
            if not passed:
                return await ctx.send("You don't have permission to use that command, or the bot lacks a required permission.")
        try:
            tokens = shlex.split(raw) if raw else []
        except ValueError as exc:
            return await ctx.send(f"Couldn't parse arguments: {exc}")
        values = {}
        cursor = 0
        for index, parameter in enumerate(params):
            required = getattr(parameter, "required", True)
            default = getattr(parameter, "default", inspect.Parameter.empty)
            annotation = getattr(parameter, "annotation", str)
            if cursor >= len(tokens):
                if required:
                    return await ctx.send(f"Missing argument: `{parameter.name}`. Use `{ctx.prefix}help` for guidance.")
                values[parameter.name] = None if default is inspect.Parameter.empty else default
                continue
            # Final string parameter receives the remaining text, allowing natural phrases.
            annotation_origin = get_origin(annotation)
            if index == len(params) - 1 and (annotation is str or getattr(annotation, "__name__", "") == "Choice" or getattr(annotation_origin, "__name__", "") == "Choice"):
                token = " ".join(tokens[cursor:])
                cursor = len(tokens)
            else:
                token = tokens[cursor]
                cursor += 1
            try:
                values[parameter.name] = await _convert_prefix_argument(
                    ctx, annotation, token, inspect.Parameter(parameter.name, inspect.Parameter.POSITIONAL_OR_KEYWORD)
                )
            except (commands.CommandError, ValueError, TypeError) as exc:
                return await ctx.send(f"Invalid `{parameter.name}`: {exc}")
        if cursor < len(tokens):
            return await ctx.send("Too many arguments. Put multi-word text in quotation marks.")
        try:
            if binding is not None:
                await callback(binding, interaction, **values)
            else:
                await callback(interaction, **values)
        except discord.Forbidden:
            await ctx.send("I don't have permission to do that. Check my role position and channel permissions.")
        except discord.HTTPException as exc:
            await ctx.send(f"Discord couldn't complete that action: {exc}")

    invoke.__name__ = f"prefix_{name.replace('-', '_')}"
    return commands.Command(invoke, name=name, help=getattr(app_command, "description", "ONYX command"))


def register_prefix_commands(bot):
    # App-command definitions remain available, but every feature also gets a prefix form.
    for app_command in bot.tree.get_commands():
        try:
            prefix_command = _register_prefix_app_command(bot, app_command)
            if bot.get_command(prefix_command.name) is None:
                bot.add_command(prefix_command)
        except Exception:
            log.exception("Could not register prefix command for %s", getattr(app_command, "name", "unknown"))


class CommunityBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=get_prefix, intents=intents)
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
        register_prefix_commands(self)
        log.info("Registered prefix command counterparts.")
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
        type=discord.ActivityType.watching, name=",help • your server"
    ))

# Replace discord.py's built-in text help command with ONYX-specific guidance.
bot.remove_command("help")


@bot.command(name="help")
async def prefix_help(ctx):
    await ctx.send(
        "ONYX commands use the comma prefix by default. Examples: `,ban @member`, `,rank`, `,ping`, `,lastfm link username`. Put multi-word text in quotation marks. Use `,prefix` to view or change this server's prefix."
    )


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

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        message = "You don't have permission to use that command."
    elif isinstance(error, commands.BotMissingPermissions):
        message = "I don't have the Discord permissions needed for that."
    elif isinstance(error, commands.MissingRequiredArgument):
        message = f"Missing argument: `{error.param.name}`. Try `,help`."
    elif isinstance(error, commands.BadArgument):
        message = str(error) or "One of the arguments wasn't recognized."
    else:
        log.error("Prefix command error", exc_info=error)
        message = "Something went wrong while running that command. Check the Render logs."
    await ctx.send(message)


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
