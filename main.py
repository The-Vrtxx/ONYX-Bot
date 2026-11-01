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
    """Bridge cog command callbacks into the prefix-command interface."""
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
    # The cog command metadata is used only to construct prefix commands; it is never published.
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
        # ONYX V6 is prefix-only. Clear any previously published global
        # application commands so Discord no longer displays slash commands.
        self.tree.clear_commands(guild=None)
        await self.tree.sync()
        log.info("Prefix-only commands registered. Database backend: %s", self.db.backend)

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

# Replace discord.py's built-in help command with an interactive ONYX help panel.
bot.remove_command("help")

HELP_CATEGORIES = {
    "Moderation": [
        ("ban", ",ban @member [reason]", "Ban a member from this server."),
        ("kick", ",kick @member [reason]", "Kick a member from this server."),
        ("timeout", ",timeout @member <minutes> [reason]", "Temporarily timeout a member."),
        ("untimeout", ",untimeout @member", "Remove a member's timeout."),
        ("warn", ",warn @member <reason>", "Record a warning."),
        ("warnings", ",warnings @member", "View a member's warning history."),
        ("purge", ",purge <amount>", "Delete recent messages."),
        ("modlogs", ",modlogs @member", "View recent moderation cases."),
        ("case", ",case <case_id>", "Look up a moderation case."),
        ("warn_escalation", ",warn_escalation <threshold> <action>", "Configure automatic action after repeated warnings."),
        ("lock", ",lock", "Lock the current text channel."),
        ("unlock", ",unlock", "Unlock the current text channel."),
        ("slowmode", ",slowmode <seconds>", "Set channel slowmode."),
    ],
    "AutoMod": [
        ("automod", ",automod", "Configure automatic moderation."),
        ("automod_ignore", ",automod_ignore #channel", "Ignore a channel in AutoMod."),
    ],
    "Logging": [("logging_set", ",logging_set #channel", "Choose the moderation log channel.")],
    "Utility": [
        ("ping", ",ping", "Check ONYX latency."),
        ("userinfo", ",userinfo [@member]", "Show member information."),
        ("serverinfo", ",serverinfo", "Show server information."),
        ("avatar", ",avatar [@member]", "Display a member's avatar."),
        ("botinfo", ",botinfo", "Show ONYX uptime and statistics."),
    ],
    "Welcome": [
        ("welcome_set", ",welcome_set #channel [message]", "Configure welcome messages."),
        ("goodbye_set", ",goodbye_set [message]", "Configure goodbye messages."),
    ],
    "Roles": [
        ("selfrole_add", ",selfrole_add @role", "Add a self-assignable role."),
        ("selfrole_remove", ",selfrole_remove @role", "Remove a self-assignable role."),
        ("selfrole_list", ",selfrole_list", "List self-assignable roles."),
        ("role", ",role @role", "Toggle a self-assignable role."),
        ("rolepanel_create", ",rolepanel_create", "Create a persistent role panel."),
    ],
    "Levels": [
        ("rank", ",rank [@member]", "View a member's level and XP."),
        ("leaderboard", ",leaderboard", "Show the server XP leaderboard."),
        ("levels_settings", ",levels_settings", "Configure XP and level-up settings."),
    ],
    "Custom Commands & Embeds": [
        ("embed", ",embed", "Create and send a custom embed."),
        ("custom_add", ",custom_add <name> <response>", "Create a custom text command."),
        ("custom_run", ",custom_run <name>", "Run a saved custom command."),
        ("custom_remove", ",custom_remove <name>", "Delete a custom command."),
        ("embed_template_save", ",embed_template_save", "Save an embed template."),
        ("embed_template_send", ",embed_template_send <name>", "Send a saved embed template."),
        ("embed_template_delete", ",embed_template_delete <name>", "Delete an embed template."),
    ],
    "Last.fm": [
        ("lastfm link", ",lastfm link <username>", "Link your Last.fm account."),
        ("lastfm nowplaying", ",lastfm nowplaying", "Show your current or latest track."),
        ("lastfm unlink", ",lastfm unlink", "Unlink your Last.fm account."),
    ],
    "Prefix": [
        ("prefix show", ",prefix show", "Show this server's prefix."),
        ("prefix set", ",prefix set <new_prefix>", "Change this server's prefix (Manage Server)."),
        ("prefix reset", ",prefix reset", "Reset this server's prefix to a comma (Manage Server)."),
    ],
    "Server Setup": [
        ("setup", ",setup", "Show the server setup checklist."),
        ("settings", ",settings", "View this server's ONYX settings."),
        ("serverdata", ",serverdata", "Explain the server data ONYX stores."),
    ],
    "Special Role": [
        ("shh", ",shh @member", "Quietly assign the configured special role."),
        ("shh_whitelist_add", ",shh_whitelist_add @member", "Allow a member to use shh (bot owner only)."),
        ("shh_whitelist_remove", ",shh_whitelist_remove @member", "Remove shh access (bot owner only)."),
        ("shh_set_role", ",shh_set_role @role", "Configure the special role (bot owner only)."),
    ],
}


def _help_embed(prefix, category=None, command=None):
    embed = discord.Embed(
        title="ONYX • Help Center",
        description=(
            f"Browse commands by category using the menus below.\n"
            f"**Current prefix:** `{prefix}`  •  **Command mode:** Prefix only\n"
            f"Choose a category, then choose a command to see what it does."
        ),
        color=discord.Color.from_rgb(25, 27, 32)
    )
    embed.set_footer(text="ONYX • Modular Discord Management")
    if category is None:
        overview = "\n".join(f"**{name}** · {len(items)} commands" for name, items in HELP_CATEGORIES.items())
        embed.add_field(name="Command Categories", value=overview, inline=False)
        embed.add_field(name="Quick start", value=f"`{prefix}ping`  ·  `{prefix}rank`  ·  `{prefix}help`", inline=False)
    else:
        items = HELP_CATEGORIES[category]
        listing = "\n".join(f"`{prefix}{usage[len(','):] if usage.startswith(',') else usage}`" for _, usage, _ in items)
        embed.add_field(name=f"{category} Commands", value=listing[:1024] or "No commands listed.", inline=False)
        if command:
            match = next((item for item in items if item[0] == command), None)
            if match:
                embed.add_field(name=match[0], value=f"**Usage:** `{prefix}{match[1][1:] if match[1].startswith(',') else match[1]}`\n{match[2]}", inline=False)
    return embed


class HelpCategorySelect(discord.ui.Select):
    def __init__(self, view):
        self.help_view = view
        options = [discord.SelectOption(label=name, description=f"Browse {len(items)} commands", value=name) for name, items in HELP_CATEGORIES.items()]
        super().__init__(placeholder="Choose a command category…", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        self.help_view.category = self.values[0]
        self.help_view.command = None
        self.help_view.refresh_command_select()
        await interaction.response.edit_message(embed=_help_embed(self.help_view.prefix, self.help_view.category), view=self.help_view)


class HelpCommandSelect(discord.ui.Select):
    def __init__(self, view):
        self.help_view = view
        super().__init__(placeholder="Choose a command for details…", min_values=1, max_values=1, options=[discord.SelectOption(label="Select a category first", value="_none")], row=1, disabled=True)

    async def callback(self, interaction: discord.Interaction):
        self.help_view.command = self.values[0]
        await interaction.response.edit_message(embed=_help_embed(self.help_view.prefix, self.help_view.category, self.help_view.command), view=self.help_view)


class OnyxHelpView(discord.ui.View):
    def __init__(self, prefix, author_id):
        super().__init__(timeout=180)
        self.prefix = prefix
        self.author_id = author_id
        self.category = None
        self.command = None
        self.category_select = HelpCategorySelect(self)
        self.command_select = HelpCommandSelect(self)
        self.add_item(self.category_select)
        self.add_item(self.command_select)

    def refresh_command_select(self):
        items = HELP_CATEGORIES.get(self.category, [])
        self.command_select.options = [
            discord.SelectOption(label=name[:100], description=description[:100], value=name)
            for name, _, description in items
        ] or [discord.SelectOption(label="No commands", value="_none")]
        self.command_select.disabled = not bool(items)
        self.command_select.placeholder = f"Choose from {self.category}…" if self.category else "Choose a command for details…"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This help menu belongs to the person who opened it. Use your server prefix followed by `help` to open your own.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


async def _send_help(ctx_or_interaction):
    guild = getattr(ctx_or_interaction, "guild", None)
    prefix = ","
    bot_instance = getattr(ctx_or_interaction, "bot", None) or getattr(ctx_or_interaction, "client", None)
    if guild and bot_instance and getattr(bot_instance, "db", None):
        row = await bot_instance.db.fetchone("SELECT prefix FROM guild_settings WHERE guild_id=?", (guild.id,))
        if row and row["prefix"]:
            prefix = row["prefix"]
    author = getattr(ctx_or_interaction, "author", None) or getattr(ctx_or_interaction, "user", None)
    view = OnyxHelpView(prefix, author.id)
    embed = _help_embed(prefix)
    if hasattr(ctx_or_interaction, "response"):
        await ctx_or_interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    else:
        await ctx_or_interaction.send(embed=embed, view=view)


@bot.command(name="help")
async def prefix_help(ctx):
    await _send_help(ctx)


