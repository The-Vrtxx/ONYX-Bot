import os
import logging
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

from database import Database
from cogs.aliases import COMMAND_ALIASES

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
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
intents.voice_states = True
intents.invites = True
intents.emojis_and_stickers = True


async def get_prefix(bot, message):
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
            log.exception(
                "Could not load prefix for guild %s; using default",
                message.guild.id
            )

    return commands.when_mentioned_or(prefix)(bot, message)


class CommunityBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=get_prefix,
            intents=intents,
            help_command=None
        )

        self.db = Database(DB_PATH, DATABASE_URL)
        self.owner_id = OWNER_ID
        self.started_at = discord.utils.utcnow()

    async def setup_hook(self):
        try:
            await self.db.connect()
            await self.db.initialize()

        except Exception as exc:
            log.critical(
                "Database startup failed (%s). Check DATABASE_URL, "
                "database availability, and database permissions.",
                type(exc).__name__,
                exc_info=True
            )

            raise RuntimeError(
                "ONYX could not connect to or initialize its database. "
                "Check the Render logs and DATABASE_URL."
            ) from exc

        loaded = []
        failed = []

        for path in sorted(Path("cogs").glob("*.py")):
            if path.name.startswith("_"):
                continue

            extension = f"cogs.{path.stem}"

            try:
                await self.load_extension(extension)
                loaded.append(path.stem)
                log.info("Loaded cog: %s", path.stem)

            except Exception as exc:
                failed.append(path.stem)

                log.exception(
                    "Could not load cog %s (%s). Other cogs will continue loading.",
                    path.stem,
                    type(exc).__name__
                )

        self.tree.clear_commands(guild=None)
        await self.tree.sync()

        log.info(
            "Startup complete. Database backend: %s | Cogs loaded: %s | Cogs failed: %s",
            self.db.backend,
            len(loaded),
            len(failed)
        )

        if failed:
            log.error("Cogs that failed to load: %s", ", ".join(failed))

    async def close(self):
        await self.db.close()
        await super().close()


bot = CommunityBot()


@bot.event
async def on_ready():
    log.info("Logged in as %s (%s)", bot.user, bot.user.id)

    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=",help • your server"
        )
    )


# =========================================================
# COMMAND ALIASES
# =========================================================

def build_alias_lookup():
    """Build shortcut -> real command path, ignoring missing/colliding entries."""

    lookup = {}
    skipped = []

    for command_path, aliases in COMMAND_ALIASES.items():
        for alias in aliases:
            key = alias.strip().lower()

            if not key or " " in key:
                continue

            if key in lookup:
                skipped.append(f"{key} (duplicate alias)")
                continue

            lookup[key] = command_path

    return lookup, skipped


async def normalize_command_alias(bot, message):
    """Translate a leading shortcut into its canonical prefix command."""

    if message.author.bot:
        return

    prefixes = await get_prefix(bot, message)

    if isinstance(prefixes, str):
        prefixes = [prefixes]

    content = message.content

    matched_prefix = next(
        (
            prefix for prefix in sorted(prefixes, key=len, reverse=True)
            if content.startswith(prefix)
        ),
        None
    )

    if not matched_prefix:
        return

    command_text = content[len(matched_prefix):]

    if not command_text:
        return

    first_token, separator, remainder = command_text.partition(" ")

    lookup, _ = build_alias_lookup()

    command_path = lookup.get(first_token.lower())

    if command_path is None:
        return

    if bot.get_command(command_path) is None:
        return

    translated = command_path.replace("_", " ")

    message.content = matched_prefix + translated + (
        separator + remainder if separator else ""
    )

    log.info(
        "Translated command alias: %r -> %r",
        content,
        message.content
    )


# =========================================================
# SPACED COMMAND SUPPORT
# =========================================================

async def normalize_spaced_command(bot, message):
    """Convert underscore command names to their spaced form."""

    if message.author.bot:
        return

    prefixes = await get_prefix(bot, message)

    if isinstance(prefixes, str):
        prefixes = [prefixes]

    content = message.content

    matched_prefix = next(
        (
            prefix for prefix in sorted(prefixes, key=len, reverse=True)
            if content.startswith(prefix)
        ),
        None
    )

    if not matched_prefix:
        return

    command_text = content[len(matched_prefix):]

    if not command_text:
        return

    candidates = []

    for command in bot.walk_commands():
        qualified = command.qualified_name
        spaced = qualified.replace("_", " ")

        if spaced != qualified:
            candidates.append((spaced, qualified))

    candidates.sort(key=lambda item: len(item[0]), reverse=True)

    lowered = command_text.lower()

    for phrase, registered_name in candidates:
        if lowered == phrase or lowered.startswith(phrase + " "):
            remainder = command_text[len(phrase):]

            message.content = matched_prefix + registered_name + remainder

            log.info(
                "Normalized command: %r -> %r",
                content,
                message.content
            )

            return


# =========================================================
# MESSAGE EVENTS
# =========================================================

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    await normalize_command_alias(bot, message)
    await normalize_spaced_command(bot, message)

    await bot.process_commands(message)


@bot.event
async def on_command_error(ctx, error):
    original = getattr(error, "original", error)

    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.CheckFailure):
        await ctx.send(
            "You don't have the permissions required for that command."
        )
        return

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            f"Missing information: `{error.param.name}`. "
            "Check `,help` for the command format."
        )
        return

    if isinstance(error, commands.BadArgument):
        await ctx.send(
            "I couldn't understand one of the arguments. "
            "Check `,help` for the command format."
        )
        return

    log.error(
        "Command error in %s from %s (guild=%s): %s",
        ctx.command.qualified_name if ctx.command else "unknown",
        ctx.author.id,
        ctx.guild.id if ctx.guild else "DM",
        repr(original),
        exc_info=(type(original), original, original.__traceback__)
    )

    try:
        await ctx.send(
            "That command ran into an error. "
            "The details have been recorded in the Render logs."
        )

    except discord.HTTPException:
        pass


# =========================================================
# OWNER-ONLY COG RELOADING
# =========================================================

@bot.group(name="reload", invoke_without_command=True)
@commands.is_owner()
async def reload_cogs(ctx, *, cog: str = None):
    """Reload one cog, or all loaded cogs. Owner only."""

    cog_files = sorted(
        path.stem for path in Path("cogs").glob("*.py")
        if not path.name.startswith("_")
    )

    if cog:
        cog = cog.strip().removeprefix("cogs.").removesuffix(".py")

        if cog not in cog_files:
            return await ctx.send(
                f"Couldn't find cog `{cog}`. Available cogs: "
                + ", ".join(f"`{name}`" for name in cog_files)
            )

        extension = f"cogs.{cog}"

        try:
            if extension in bot.extensions:
                await bot.reload_extension(extension)
            else:
                await bot.load_extension(extension)

            return await ctx.send(
                f"Reloaded `{cog}` successfully."
            )

        except Exception as exc:
            log.exception("Failed to reload extension %s", extension)

            return await ctx.send(
                f"Couldn't reload `{cog}`: "
                f"`{type(exc).__name__}: {exc}`"
            )

    succeeded = []
    failed = []

    for name in cog_files:
        extension = f"cogs.{name}"

        try:
            if extension in bot.extensions:
                await bot.reload_extension(extension)
            else:
                await bot.load_extension(extension)

            succeeded.append(name)

        except Exception as exc:
            log.exception("Failed to reload extension %s", extension)
            failed.append(f"{name}: {type(exc).__name__}: {exc}")

    summary = (
        f"Reload complete. **{len(succeeded)}** loaded/reloaded."
    )

    if succeeded:
        summary += (
            "\n**Successful:** "
            + ", ".join(f"`{name}`" for name in succeeded)
        )

    if failed:
        summary += "\n**Failed:** " + "; ".join(failed)

    await ctx.send(summary)


# =========================================================
# HELP MENU SETTINGS
# =========================================================

COG_LABELS = {
    "automod": "AutoMod",
    "channel_manager": "Channel Management",
    "custom": "Custom Commands & Embeds",
    "engagement": "Engagement",
    "lastfm": "Last.fm",
    "levels": "Levels",
    "logging": "Logging",
    "member_tools": "Member Tools",
    "moderation": "Moderation",
    "moderation_plus": "Moderation Extras",
    "prefix": "Prefix",
    "protection": "Anti-Raid Protection",
    "roles": "Roles",
    "security": "Security",
    "server_setup": "Server Setup",
    "server_tools": "Server Tools",
    "shh": "Special Role",
    "tickets": "Tickets",
    "utility": "Utility",
    "voicemaster": "Voice Master",
    "welcome": "Welcome & Goodbye",
}

COMMANDS_PER_PAGE = 4


def get_help_categories():
    categories = {}

    for command in bot.walk_commands():
        if command.hidden:
            continue

        label = COG_LABELS.get(
            command.cog.__class__.__module__.split(".")[-1]
            if command.cog else "core",
            command.cog.qualified_name if command.cog else "Core"
        )

        categories.setdefault(label, []).append(command)

    for items in categories.values():
        items.sort(
            key=lambda item: item.qualified_name.casefold()
        )

    return dict(
        sorted(
            categories.items(),
            key=lambda item: item[0].casefold()
        )
    )


def _command_usage(prefix, command):
    usage = f"{prefix}{command.qualified_name}"

    if command.signature:
        usage += f" {command.signature}"

    return usage


def _help_embed(prefix, category=None, page=0):
    categories = get_help_categories()

    embed = discord.Embed(
        title="ONYX" if category is None else f"ONYX • {category}",
        color=discord.Color.from_rgb(44, 38, 67)
    )

    if category is None:
        total_commands = sum(
            len(items) for items in categories.values()
        )

        embed.description = "\n".join([
            "Welcome to the ONYX help menu.",
            "",
            "Choose a category below to browse its commands.",
            f"**{len(categories)} categories • {total_commands} commands**",
            "",
            f"Use `{prefix}help <command>` for details about a command."
        ])

    else:
        items = categories.get(category, [])

        total_pages = max(
            1,
            (len(items) + COMMANDS_PER_PAGE - 1) // COMMANDS_PER_PAGE
        )

        page = max(0, min(page, total_pages - 1))

        page_items = items[
            page * COMMANDS_PER_PAGE:
            (page + 1) * COMMANDS_PER_PAGE
        ]

        lines = []

        for command in page_items:
            description = (
                command.help
                or command.brief
                or "No description available."
            )

            lines.append(
                f"`{_command_usage(prefix, command)}`\n"
                f"{description[:180]}"
            )

        embed.description = (
            "\n\n".join(lines)
            + f"\n\n`{prefix}help <command>` for more details"
            + (
                f" • Page {page + 1}/{total_pages}"
                if total_pages > 1 else ""
            )
        )

    embed.set_footer(text="ONYX • Prefix Commands Only")

    return embed


# =========================================================
# HELP CATEGORY DROPDOWN
# =========================================================

class HelpCategorySelect(discord.ui.Select):
    def __init__(self, view):
        self.help_view = view

        categories = get_help_categories()

        options = [
            discord.SelectOption(
                label=name[:100],
                description=f"{len(items)} commands",
                value=name
            )
            for name, items in categories.items()
        ][:25]

        super().__init__(
            placeholder="Select a command category...",
            min_values=1,
            max_values=1,
            options=options,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        self.help_view.category = self.values[0]
        self.help_view.page = 0

        self.help_view.refresh_pagination_controls()

        await interaction.response.edit_message(
            embed=_help_embed(
                self.help_view.prefix,
                self.help_view.category,
                self.help_view.page
            ),
            view=self.help_view
        )


# =========================================================
# INTERACTIVE HELP MENU
# =========================================================

class OnyxHelpView(discord.ui.View):
    def __init__(self, prefix, author_id):
        super().__init__(timeout=180)

        self.prefix = prefix
        self.author_id = author_id
        self.category = None
        self.page = 0

        self.category_select = HelpCategorySelect(self)
        self.add_item(self.category_select)

        self.previous_button = discord.ui.Button(
            label="Previous",
            style=discord.ButtonStyle.secondary,
            emoji="◀️",
            row=1,
            disabled=True
        )

        self.next_button = discord.ui.Button(
            label="Next",
            style=discord.ButtonStyle.secondary,
            emoji="▶️",
            row=1
        )

        self.previous_button.callback = self._previous_page
        self.next_button.callback = self._next_page

        self._pagination_added = False

    def _page_count(self):
        count = len(
            get_help_categories().get(self.category, [])
        )

        return max(
            1,
            (count + COMMANDS_PER_PAGE - 1) // COMMANDS_PER_PAGE
        )

    def refresh_pagination_controls(self):
        total_pages = self._page_count()

        if total_pages > 1 and not self._pagination_added:
            self.add_item(self.previous_button)
            self.add_item(self.next_button)
            self._pagination_added = True

        elif total_pages <= 1 and self._pagination_added:
            self.remove_item(self.previous_button)
            self.remove_item(self.next_button)
            self._pagination_added = False

        if self._pagination_added:
            self.previous_button.disabled = self.page <= 0
            self.next_button.disabled = (
                self.page >= total_pages - 1
            )

    async def _change_page(self, interaction, direction):
        total_pages = self._page_count()
        new_page = self.page + direction

        if not 0 <= new_page < total_pages:
            return await interaction.response.defer()

        self.page = new_page
        self.refresh_pagination_controls()

        await interaction.response.edit_message(
            embed=_help_embed(
                self.prefix,
                self.category,
                self.page
            ),
            view=self
        )

    async def _previous_page(self, interaction):
        await self._change_page(interaction, -1)

    async def _next_page(self, interaction):
        await self._change_page(interaction, 1)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This help menu belongs to the person who opened it. "
                "Use `,help` to open your own.",
                ephemeral=True
            )

            return False

        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# =========================================================
# HELP COMMAND LOOKUP
# =========================================================

async def _send_help(ctx, command_query=None):
    prefix = ctx.prefix

    if command_query:
        query = command_query.strip().casefold()

        # Resolve regular command names and Discord.py aliases first.
        command = bot.get_command(
            query.replace(" ", "_")
        )

        if command is None:
            command = bot.get_command(query)

        # Resolve shortcuts from cogs/aliases.py.
        if command is None:
            for command_path, shortcuts in COMMAND_ALIASES.items():
                if query in {
                    shortcut.casefold()
                    for shortcut in shortcuts
                }:
                    command = bot.get_command(command_path)

                    if command is not None:
                        break

        # Never reveal hidden commands through public help.
        if command is None or command.hidden:
            return await ctx.send(
                f"I couldn't find `{command_query}`. "
                f"Use `{prefix}help` to browse commands."
            )

        embed = discord.Embed(
            title=f"ONYX • {command.qualified_name}",
            description=(
                f"**Usage:** `{_command_usage(prefix, command)}`\n"
                f"**Description:** "
                f"{command.help or command.brief or 'No description available.'}"
            ),
            color=discord.Color.from_rgb(44, 38, 67)
        )

        embed.set_footer(
            text="ONYX • Prefix Commands Only"
        )

        return await ctx.send(embed=embed)

    view = OnyxHelpView(prefix, ctx.author.id)

    await ctx.send(
        embed=_help_embed(prefix),
        view=view
    )


# =========================================================
# OWNER-ONLY HIDDEN COMMAND DIRECTORY
# =========================================================

@bot.command(
    name="ownerhelp",
    aliases=["ownercommands", "hiddencommands"],
    hidden=True
)
@commands.is_owner()
async def owner_help(ctx):
    """Show all currently loaded hidden commands. Bot owner only."""

    hidden_commands = sorted(
        (
            command for command in bot.walk_commands()
            if command.hidden
        ),
        key=lambda command: command.qualified_name.casefold()
    )

    if not hidden_commands:
        return await ctx.send(
            "No hidden commands are currently loaded."
        )

    lines = []

    for command in hidden_commands:
        usage = _command_usage(ctx.prefix, command)

        description = (
            command.help
            or command.brief
            or "No description available."
        )

        lines.append(
            f"`{usage}`\n"
            f"{description[:160]}"
        )

    # Split long directories across multiple embeds.
    pages = []
    current = []
    current_length = 0

    for line in lines:
        line_length = len(line) + 2

        if current and current_length + line_length > 3800:
            pages.append(current)
            current = []
            current_length = 0

        current.append(line)
        current_length += line_length

    if current:
        pages.append(current)

    for index, page_lines in enumerate(pages, start=1):
        embed = discord.Embed(
            title="ONYX • Owner Command Directory",
            description="\n\n".join(page_lines),
            color=discord.Color.from_rgb(44, 38, 67)
        )

        embed.set_footer(
            text=(
                f"Owner only • {len(hidden_commands)} hidden commands "
                f"• Page {index}/{len(pages)}"
            )
        )

        await ctx.send(embed=embed)


# =========================================================
# PUBLIC HELP COMMAND
# =========================================================

@bot.command(name="help")
async def prefix_help(ctx, *, command: str = None):
    await _send_help(ctx, command)


# =========================================================
# START BOT
# =========================================================

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN is missing. Add it to Render's environment "
            "variables or your local .env file. Never commit the real token."
        )

    if not OWNER_ID:
        log.warning(
            "BOT_OWNER_ID is not set. Owner-only commands may not work "
            "until you configure it."
        )

    bot.run(TOKEN)
