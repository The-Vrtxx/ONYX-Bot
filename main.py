import os
import logging
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

from database import Database
from cogs.aliases import COMMAND_ALIASES

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
intents.voice_states = True
intents.invites = True
intents.emojis_and_stickers = True


async def get_prefix(bot, message):
    prefix = ","
    if message.guild and getattr(bot, "db", None):
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


class CommunityBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=get_prefix, intents=intents, help_command=None)
        self.db = Database(DB_PATH, DATABASE_URL)
        self.owner_id = OWNER_ID
        self.started_at = discord.utils.utcnow()

    async def setup_hook(self):
        try:
            await self.db.connect()
            await self.db.initialize()
        except Exception as exc:
            log.critical(
                "Database startup failed (%s). Check DATABASE_URL, database availability, and permissions.",
                type(exc).__name__, exc_info=True
            )
            raise RuntimeError(
                "ONYX could not connect to or initialize its database. Check Render logs and DATABASE_URL."
            ) from exc

        loaded, failed = [], []
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
                log.exception("Could not load cog %s (%s).", path.stem, type(exc).__name__)

        self.tree.clear_commands(guild=None)
        await self.tree.sync()
        log.info(
            "Startup complete. Database backend: %s | Cogs loaded: %s | Cogs failed: %s",
            self.db.backend, len(loaded), len(failed)
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
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name=",help • your server"
    ))


def build_alias_lookup():
    lookup, skipped = {}, []
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


async def _prefixes(bot, message):
    prefixes = await get_prefix(bot, message)
    return [prefixes] if isinstance(prefixes, str) else prefixes


async def normalize_command_alias(bot, message):
    if message.author.bot:
        return
    prefixes = await _prefixes(bot, message)
    content = message.content
    prefix = next((p for p in sorted(prefixes, key=len, reverse=True) if content.startswith(p)), None)
    if not prefix:
        return
    command_text = content[len(prefix):]
    if not command_text:
        return
    token, separator, remainder = command_text.partition(" ")
    command_path = build_alias_lookup()[0].get(token.lower())
    if command_path is None or bot.get_command(command_path) is None:
        return
    message.content = prefix + command_path.replace("_", " ") + (separator + remainder if separator else "")
    log.info("Translated command alias: %r -> %r", content, message.content)


async def normalize_spaced_command(bot, message):
    if message.author.bot:
        return
    prefixes = await _prefixes(bot, message)
    content = message.content
    prefix = next((p for p in sorted(prefixes, key=len, reverse=True) if content.startswith(p)), None)
    if not prefix:
        return
    command_text = content[len(prefix):]
    if not command_text:
        return
    candidates = []
    for command in bot.walk_commands():
        name = command.qualified_name
        spaced = name.replace("_", " ")
        if spaced != name:
            candidates.append((spaced, name))
    for phrase, registered in sorted(candidates, key=lambda item: len(item[0]), reverse=True):
        if command_text.lower() == phrase or command_text.lower().startswith(phrase + " "):
            message.content = prefix + registered + command_text[len(phrase):]
            log.info("Normalized command: %r -> %r", content, message.content)
            return


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
        return await ctx.send("You don't have the permissions required for that command.")
    if isinstance(error, commands.MissingRequiredArgument):
        return await ctx.send(
            f"Missing information: `{error.param.name}`. Check `,help` for the command format."
        )
    if isinstance(error, commands.BadArgument):
        return await ctx.send("I couldn't understand one of the arguments. Check `,help` for the command format.")
    log.error(
        "Command error in %s from %s (guild=%s): %s",
        ctx.command.qualified_name if ctx.command else "unknown",
        ctx.author.id, ctx.guild.id if ctx.guild else "DM", repr(original),
        exc_info=(type(original), original, original.__traceback__)
    )
    try:
        await ctx.send("That command ran into an error. The details have been recorded in the Render logs.")
    except discord.HTTPException:
        pass


@bot.group(name="reload", invoke_without_command=True)
@commands.is_owner()
async def reload_cogs(ctx, *, cog: str = None):
    """Reload one cog, or all loaded cogs. Owner only."""
    files = sorted(p.stem for p in Path("cogs").glob("*.py") if not p.name.startswith("_"))
    if cog:
        cog = cog.strip().removeprefix("cogs.").removesuffix(".py")
        if cog not in files:
            return await ctx.send(
                f"Couldn't find cog `{cog}`. Available cogs: " +
                ", ".join(f"`{name}`" for name in files)
            )
        extension = f"cogs.{cog}"
        try:
            if extension in bot.extensions:
                await bot.reload_extension(extension)
            else:
                await bot.load_extension(extension)
            return await ctx.send(f"Reloaded `{cog}` successfully.")
        except Exception as exc:
            log.exception("Failed to reload extension %s", extension)
            return await ctx.send(f"Couldn't reload `{cog}`: `{type(exc).__name__}: {exc}`")

    good, bad = [], []
    for name in files:
        extension = f"cogs.{name}"
        try:
            if extension in bot.extensions:
                await bot.reload_extension(extension)
            else:
                await bot.load_extension(extension)
            good.append(name)
        except Exception as exc:
            log.exception("Failed to reload extension %s", extension)
            bad.append(f"{name}: {type(exc).__name__}: {exc}")
    message = f"Reload complete. **{len(good)}** loaded/reloaded."
    if good:
        message += "\n**Successful:** " + ", ".join(f"`{n}`" for n in good)
    if bad:
        message += "\n**Failed:** " + "; ".join(bad)
    await ctx.send(message)


COG_LABELS = {
    "automod": "AutoMod", "channel_manager": "Channel Management",
    "custom": "Custom Commands & Embeds", "engagement": "Engagement",
    "lastfm": "Last.fm", "levels": "Levels", "logging": "Logging",
    "member_tools": "Member Tools", "moderation": "Moderation",
    "moderation_plus": "Moderation Extras", "prefix": "Prefix",
    "protection": "Anti-Raid Protection", "roles": "Roles",
    "security": "Security", "server_setup": "Server Setup",
    "server_tools": "Server Tools", "shh": "Special Role",
    "tickets": "Tickets", "utility": "Utility", "voicemaster": "Voice Master",
    "welcome": "Welcome & Goodbye", "reports": "Reports",
}
COMMANDS_PER_PAGE = 4
GROUP_OPTIONS_PER_PAGE = 25


def get_help_categories():
    categories = {}
    for command in bot.walk_commands():
        if command.hidden:
            continue
        module = command.cog.__class__.__module__.split(".")[-1] if command.cog else "core"
        label = COG_LABELS.get(module, command.cog.qualified_name if command.cog else "Core")
        categories.setdefault(label, []).append(command)
    for commands_in_category in categories.values():
        commands_in_category.sort(key=lambda c: c.qualified_name.casefold())
    return dict(sorted(categories.items(), key=lambda item: item[0].casefold()))


def _command_usage(prefix, command):
    usage = f"{prefix}{command.qualified_name}"
    if command.signature:
        usage += f" {command.signature}"
    return usage


def _command_detail_embed(prefix, command):
    embed = discord.Embed(
        title=f"ONYX • {command.qualified_name}",
        description=(
            f"**Usage:** `{_command_usage(prefix, command)}`\n"
            f"**Description:** {command.help or command.brief or 'No description available.'}"
        ),
        color=discord.Color.from_rgb(44, 38, 67)
    )
    embed.set_footer(text="ONYX • Prefix Commands Only")
    return embed


def _help_embed(prefix, category=None, page=0):
    categories = get_help_categories()
    embed = discord.Embed(
        title="ONYX" if category is None else f"ONYX • {category}",
        url="https://onyxdiscord.com",
        color=discord.Color.from_rgb(44, 38, 67)
    )
    if category is None:
        total = sum(len(items) for items in categories.values())
        embed.description = "\n".join([
            "Welcome to the ONYX help menu.", "",
            "Choose a category below to browse its commands.",
            f"**{len(categories)} categories • {total} commands**", "",
            f"Use `{prefix}help <command>` for details about a command."
        ])
    else:
        items = categories.get(category, [])
        pages = max(1, (len(items) + COMMANDS_PER_PAGE - 1) // COMMANDS_PER_PAGE)
        page = max(0, min(page, pages - 1))
        subset = items[page * COMMANDS_PER_PAGE:(page + 1) * COMMANDS_PER_PAGE]
        lines = [
            f"`{_command_usage(prefix, cmd)}`\n{(cmd.help or cmd.brief or 'No description available.')[:180]}"
            for cmd in subset
        ]
        embed.description = "\n\n".join(lines) + f"\n\n`{prefix}help <command>` for more details"
        if pages > 1:
            embed.description += f" • Page {page + 1}/{pages}"
    embed.set_footer(text="ONYX • Prefix Commands Only")
    return embed


def _visible_group_commands(group):
    return sorted(
        (child for child in group.walk_commands() if not child.hidden),
        key=lambda child: child.qualified_name.casefold()
    )


def _group_help_embed(prefix, group, page=0, selected=None):
    if selected is not None:
        embed = _command_detail_embed(prefix, selected)
        embed.description += f"\n\nSelect another **{group.qualified_name}** command below to view its details."
        return embed
    children = _visible_group_commands(group)
    pages = max(1, (len(children) + GROUP_OPTIONS_PER_PAGE - 1) // GROUP_OPTIONS_PER_PAGE)
    page = max(0, min(page, pages - 1))
    subset = children[page * GROUP_OPTIONS_PER_PAGE:(page + 1) * GROUP_OPTIONS_PER_PAGE]
    lines = [
        f"`{_command_usage(prefix, child)}` — {(child.short_doc or child.brief or 'No description available.')[:120]}"
        for child in subset
    ]
    embed = discord.Embed(
        title=f"ONYX • {group.qualified_name.title()} Commands",
        description=(
            "Choose any command from the dropdown to see its full usage and description.\n\n"
            + ("\n".join(lines) if lines else "This group has no visible subcommands.")
        ),
        color=discord.Color.from_rgb(44, 38, 67)
    )
    embed.set_footer(text=f"{len(children)} commands • Page {page + 1}/{pages} • ONYX Help")
    return embed


class HelpCategorySelect(discord.ui.Select):
    def __init__(self, view):
        self.help_view = view
        options = [
            discord.SelectOption(label=name[:100], description=f"{len(items)} commands", value=name)
            for name, items in get_help_categories().items()
        ][:25]
        super().__init__(placeholder="Select a command category...", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction):
        self.help_view.category = self.values[0]
        self.help_view.page = 0
        self.help_view.refresh_controls()
        await interaction.response.edit_message(
            embed=_help_embed(self.help_view.prefix, self.help_view.category, 0),
            view=self.help_view
        )


class OnyxHelpView(discord.ui.View):
    def __init__(self, prefix, author_id):
        super().__init__(timeout=180)
        self.prefix, self.author_id = prefix, author_id
        self.category, self.page = None, 0
        self.add_item(HelpCategorySelect(self))
        self.previous_button = discord.ui.Button(label="Previous", style=discord.ButtonStyle.secondary, emoji="◀️", row=1, disabled=True)
        self.next_button = discord.ui.Button(label="Next", style=discord.ButtonStyle.secondary, emoji="▶️", row=1)
        self.previous_button.callback = self.previous
        self.next_button.callback = self.next
        self.pagination_added = False

    def refresh_controls(self):
        count = len(get_help_categories().get(self.category, []))
        pages = max(1, (count + COMMANDS_PER_PAGE - 1) // COMMANDS_PER_PAGE)
        if pages > 1 and not self.pagination_added:
            self.add_item(self.previous_button)
            self.add_item(self.next_button)
            self.pagination_added = True
        elif pages <= 1 and self.pagination_added:
            self.remove_item(self.previous_button)
            self.remove_item(self.next_button)
            self.pagination_added = False
        if self.pagination_added:
            self.previous_button.disabled = self.page <= 0
            self.next_button.disabled = self.page >= pages - 1

    async def change_page(self, interaction, delta):
        pages = max(1, (len(get_help_categories().get(self.category, [])) + COMMANDS_PER_PAGE - 1) // COMMANDS_PER_PAGE)
        target = self.page + delta
        if not 0 <= target < pages:
            return await interaction.response.defer()
        self.page = target
        self.refresh_controls()
        await interaction.response.edit_message(embed=_help_embed(self.prefix, self.category, self.page), view=self)

    async def previous(self, interaction):
        await self.change_page(interaction, -1)

    async def next(self, interaction):
        await self.change_page(interaction, 1)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This help menu belongs to the person who opened it. Use `,help` to open your own.",
                ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class GroupCommandSelect(discord.ui.Select):
    def __init__(self, view):
        self.group_view = view
        options = view.get_options()
        super().__init__(placeholder="Choose a command to view its details...", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction):
        selected = bot.get_command(self.values[0])
        if selected is None or selected.hidden:
            return await interaction.response.send_message("That command is no longer available.", ephemeral=True)
        self.group_view.selected = selected
        await interaction.response.edit_message(
            embed=_group_help_embed(self.group_view.prefix, self.group_view.group, self.group_view.page, selected),
            view=self.group_view
        )


class GroupHelpView(discord.ui.View):
    def __init__(self, prefix, author_id, group):
        super().__init__(timeout=180)
        self.prefix, self.author_id, self.group = prefix, author_id, group
        self.page, self.selected = 0, None
        self.commands = _visible_group_commands(group)
        self.command_select = GroupCommandSelect(self)
        self.add_item(self.command_select)
        self.previous_button = discord.ui.Button(label="Previous commands", style=discord.ButtonStyle.secondary, emoji="◀️", row=1, disabled=True)
        self.next_button = discord.ui.Button(label="More commands", style=discord.ButtonStyle.secondary, emoji="▶️", row=1)
        self.previous_button.callback = self.previous
        self.next_button.callback = self.next
        self.pagination_added = False
        self.refresh_controls()

    def get_options(self):
        subset = self.commands[self.page * GROUP_OPTIONS_PER_PAGE:(self.page + 1) * GROUP_OPTIONS_PER_PAGE]
        return [
            discord.SelectOption(
                label=child.qualified_name[:100],
                description=(child.short_doc or child.brief or "View command details")[:100],
                value=child.qualified_name
            )
            for child in subset
        ] or [discord.SelectOption(label="No visible subcommands", value=self.group.qualified_name, description="This group has no visible subcommands.")]

    def refresh_controls(self):
        pages = max(1, (len(self.commands) + GROUP_OPTIONS_PER_PAGE - 1) // GROUP_OPTIONS_PER_PAGE)
        if pages > 1 and not self.pagination_added:
            self.add_item(self.previous_button)
            self.add_item(self.next_button)
            self.pagination_added = True
        elif pages <= 1 and self.pagination_added:
            self.remove_item(self.previous_button)
            self.remove_item(self.next_button)
            self.pagination_added = False
        if self.pagination_added:
            self.previous_button.disabled = self.page <= 0
            self.next_button.disabled = self.page >= pages - 1

    async def change_page(self, interaction, delta):
        pages = max(1, (len(self.commands) + GROUP_OPTIONS_PER_PAGE - 1) // GROUP_OPTIONS_PER_PAGE)
        target = self.page + delta
        if not 0 <= target < pages:
            return await interaction.response.defer()
        self.page, self.selected = target, None
        self.remove_item(self.command_select)
        self.command_select = GroupCommandSelect(self)
        self.add_item(self.command_select)
        self.refresh_controls()
        await interaction.response.edit_message(embed=_group_help_embed(self.prefix, self.group, self.page), view=self)

    async def previous(self, interaction):
        await self.change_page(interaction, -1)

    async def next(self, interaction):
        await self.change_page(interaction, 1)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This help menu belongs to the person who opened it. Use `,help` to open your own.",
                ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


async def _send_help(ctx, command_query=None):
    prefix = ctx.prefix
    if command_query:
        query = command_query.strip().casefold()
        command = bot.get_command(query.replace(" ", "_")) or bot.get_command(query)
        if command is None:
            for path, aliases in COMMAND_ALIASES.items():
                if query in {alias.casefold() for alias in aliases}:
                    command = bot.get_command(path)
                    if command is not None:
                        break
        if command is None or command.hidden:
            return await ctx.send(f"I couldn't find `{command_query}`. Use `{prefix}help` to browse commands.")
        if isinstance(command, commands.Group) and _visible_group_commands(command):
            return await ctx.send(
                embed=_group_help_embed(prefix, command),
                view=GroupHelpView(prefix, ctx.author.id, command)
            )
        return await ctx.send(embed=_command_detail_embed(prefix, command))
    await ctx.send(embed=_help_embed(prefix), view=OnyxHelpView(prefix, ctx.author.id))


# =========================================================
# OWNER-ONLY CATEGORIZED COMMAND DIRECTORY
# =========================================================

def _is_owner_restricted(command):
    return any("is_owner" in getattr(check, "__qualname__", "") for check in getattr(command, "checks", []))


def _owner_category(command):
    module = command.cog.__class__.__module__.split(".")[-1] if command.cog else "core"
    labels = {
        "reports": "Reports", "moderation": "Moderation",
        "moderation_plus": "Moderation Extras", "automod": "AutoMod & Filters",
        "security": "Security & Protection", "protection": "Anti-Raid Protection",
        "backup": "Backups", "logging": "Logging", "levels": "Levels & Engagement",
        "roles": "Roles", "member_tools": "Member Tools", "server_setup": "Server Setup",
        "server_tools": "Server Tools", "tickets": "Tickets",
        "channel_manager": "Channel Management", "utility": "Utilities",
        "core": "Core / Owner Tools",
    }
    return labels.get(module, module.replace("_", " ").title())


@bot.command(name="ownerhelp", aliases=["ownercommands", "hiddencommands"], hidden=True)
@commands.is_owner()
async def owner_help(ctx):
    """Show hidden and owner-restricted commands, organized by category."""
    selected = []
    for command in bot.walk_commands():
        if (
            command.hidden
            or _is_owner_restricted(command)
            or command.qualified_name in {"setupreport", "reload"}
        ):
            selected.append(command)

    if not selected:
        return await ctx.send("No hidden or owner-restricted commands are currently loaded.")

    categories = {}
    for command in selected:
        categories.setdefault(_owner_category(command), []).append(command)

    blocks, current, current_length = [], [], 0
    for category in sorted(categories, key=str.casefold):
        commands_in_category = sorted(categories[category], key=lambda c: c.qualified_name.casefold())
        lines = [f"**{category}**"]
        for command in commands_in_category:
            usage = _command_usage(ctx.prefix, command)
            description = command.help or command.brief or "No description available."
            lines.append(f"`{usage}`\n{description[:180]}")
        block = "\n".join(lines)
        if current and current_length + len(block) + 3 > 3800:
            blocks.append("\n\n".join(current))
            current, current_length = [], 0
        current.append(block)
        current_length += len(block) + 3
    if current:
        blocks.append("\n\n".join(current))

    for index, page in enumerate(blocks, start=1):
        embed = discord.Embed(
            title="ONYX • Owner Command Directory",
            description=page,
            color=discord.Color.from_rgb(44, 38, 67)
        )
        embed.set_footer(text=(
            f"Bot owner only • {len(selected)} commands across "
            f"{len(categories)} categories • Page {index}/{len(blocks)}"
        ))
        await ctx.send(embed=embed)


@bot.command(name="help")
async def prefix_help(ctx, *, command: str = None):
    await _send_help(ctx, command)


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN is missing. Add it to Render's environment variables "
            "or your local .env file. Never commit the real token."
        )
    if not OWNER_ID:
        log.warning("BOT_OWNER_ID is not set. Owner-only commands may not work until configured.")
    bot.run(TOKEN)
