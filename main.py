import os
import logging
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

from database import Database

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
        await self.db.connect()
        await self.db.initialize()

        for path in sorted(Path("cogs").glob("*.py")):
            if path.name.startswith("_"):
                continue

            await self.load_extension(f"cogs.{path.stem}")
            log.info("Loaded %s", path.stem)

        # Remove legacy global slash commands.
        # ONYX uses prefix commands only.
        self.tree.clear_commands(guild=None)
        await self.tree.sync()

        log.info(
            "Prefix-only command system ready. Database backend: %s",
            self.db.backend
        )

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


async def normalize_spaced_command(bot, message):
    """
    Convert commands containing spaces into their registered
    underscore command names.

    Example:
    ,shh whitelist add @member

    Becomes:
    ,shh_whitelist_add @member

    Only the command name is changed. Arguments are preserved.
    """

    if message.guild is None or message.author.bot:
        return

    prefixes = await get_prefix(bot, message)

    if isinstance(prefixes, str):
        prefixes = [prefixes]

    content = message.content

    matched_prefix = next(
        (
            prefix
            for prefix in sorted(prefixes, key=len, reverse=True)
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

    candidates.sort(
        key=lambda item: len(item[0]),
        reverse=True
    )

    lowered = command_text.lower()

    for phrase, registered_name in candidates:
        if lowered == phrase or lowered.startswith(phrase + " "):
            remainder = command_text[len(phrase):]
            original_content = message.content

            message.content = (
                matched_prefix
                + registered_name
                + remainder
            )

            log.info(
                "Normalized command: %r -> %r",
                original_content,
                message.content
            )
            return


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    await normalize_spaced_command(bot, message)
    await bot.process_commands(message)


@bot.event
async def on_command_error(ctx, error):
    original = getattr(error, "original", error)

    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.CheckFailure):
        await ctx.send(
            "You need to be the server owner or have Manage Server "
            "permission to use this command."
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
        exc_info=(
            type(original),
            original,
            original.__traceback__
        )
    )

    try:
        await ctx.send(
            "That command ran into an error. "
            "The details have been recorded in the Render logs."
        )
    except discord.HTTPException:
        pass


@bot.group(name="reload", invoke_without_command=True)
@commands.is_owner()
async def reload_cogs(ctx, *, cog: str = None):
    """Reload one cog, or all loaded cogs. Owner only."""

    cog_files = sorted(
        path.stem
        for path in Path("cogs").glob("*.py")
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

            return await ctx.send(f"Reloaded `{cog}` successfully.")

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

    summary = f"Reload complete. **{len(succeeded)}** loaded/reloaded."

    if succeeded:
        summary += "\n**Successful:** " + ", ".join(
            f"`{name}`" for name in succeeded
        )

    if failed:
        summary += "\n**Failed:** " + "; ".join(failed)

    await ctx.send(summary)


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
        ("warn_escalation", ",warn_escalation <threshold> <timeout|kick|ban>", "Configure automatic action after repeated warnings."),
        ("lock", ",lock", "Lock the current text channel."),
        ("unlock", ",unlock", "Unlock the current text channel."),
        ("slowmode", ",slowmode <seconds>", "Set channel slowmode."),
    ],
    "AutoMod": [
        ("automod", ",automod <enabled> [block_invites] [block_links] [spam_limit]", "Configure automatic moderation."),
        ("automod_ignore", ",automod ignore #channel", "Ignore a channel in AutoMod."),
    ],
    "Logging": [
        ("logging_set", ",logging set #channel", "Set the server's logging destination."),
        ("logging_remove", ",logging remove [#channel]", "Remove the configured logging destination."),
        ("logging_list", ",logging list", "Show the current logging destination."),
        ("logging_test", ",logging test", "Send a test log."),
    ],
    "Channel Management": [
        ("channel", ",channel", "Show channel management commands."),
        ("channel create", ",channel create <name>", "Create a text channel."),
        ("channel delete", ",channel delete #channel", "Delete a text channel after confirmation."),
        ("nuke", ",nuke", "Recreate the current channel while preserving its settings."),
    ],
    "Utility": [
        ("ping", ",ping", "Check ONYX latency."),
        ("userinfo", ",userinfo [@member]", "Show member information."),
        ("serverinfo", ",serverinfo", "Show server information."),
        ("avatar", ",avatar [@member]", "Display a member's avatar."),
        ("botinfo", ",botinfo", "Show ONYX uptime and statistics."),
    ],
    "Welcome": [
        ("welcome_set", ",welcome set #channel message...", "Configure welcome messages."),
        ("goodbye_set", ",goodbye set message...", "Configure goodbye messages."),
    ],
    "Roles": [
        ("selfrole_add", ",selfrole add @role", "Add a self-assignable role."),
        ("selfrole_remove", ",selfrole remove @role", "Remove a self-assignable role."),
        ("selfrole_list", ",selfrole list", "List self-assignable roles."),
        ("role", ",role @role", "Toggle a self-assignable role."),
        ("rolepanel_create", ",rolepanel create", "Create a persistent role panel."),
    ],
    "Levels": [
        ("rank", ",rank [@member]", "View a member's level and XP."),
        ("leaderboard", ",leaderboard", "Show the server XP leaderboard."),
        ("levels_settings", ",levels settings <enabled> [#channel]", "Configure XP and level-up settings."),
    ],
    "Custom Commands & Embeds": [
        ("embed", ",embed <title> <description>", "Create and send a custom embed."),
        ("custom_add", ",custom add <name> <response>", "Create a custom text command."),
        ("custom_run", ",custom run <name>", "Run a saved custom command."),
        ("custom_remove", ",custom remove <name>", "Delete a custom command."),
        ("embed_template_save", ",embed template save <name> <title> <description>", "Save an embed template."),
        ("embed_template_send", ",embed template send <name>", "Send a saved embed template."),
        ("embed_template_delete", ",embed template delete <name>", "Delete a saved embed template."),
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
        ("reload", ",reload [cog]", "Reload one cog or all cogs (bot owner only)."),
    ],
    "Moderation Extras": [
        ("modnote", ",modnote @member <note>", "Save a staff-only note."),
        ("modnotes", ",modnotes @member", "View staff-only notes."),
        ("nick", ",nick @member <nickname>", "Change a member nickname."),
        ("role_add", ",role_add @member @role", "Give a member a role."),
        ("role_remove", ",role_remove @member @role", "Remove a member role."),
    ],
    "Security": [
        ("security_set", ",security_set #channel", "Set security alert destination."),
        ("security_off", ",security_off", "Disable security alerts."),
    ],
    "Server Tools": [
        ("channelcount", ",channelcount", "Show channel counts."),
        ("rolelist", ",rolelist", "List server roles."),
        ("emoji_list", ",emoji_list", "List custom server emojis."),
        ("permissions", ",permissions [@member]", "Show key permissions."),
    ],
    "Engagement": [
        ("poll", ",poll <question>", "Create a community poll."),
        ("autoresponse_add", ",autoresponse_add <trigger> <response>", "Add an automatic response."),
        ("autoresponse_remove", ",autoresponse_remove <trigger>", "Remove an automatic response."),
        ("autoresponse_list", ",autoresponse_list", "List automatic responses."),
    ],
    "Tickets": [
        ("ticket_setup", ",ticket_setup", "Create a support ticket panel."),
    ],
    "Voice Master": [
        ("voicemaster_set", ",voicemaster_set <channel>", "Set the voice room creation channel."),
        ("voicemaster_remove", ",voicemaster_remove", "Remove the voice room creation channel."),
        ("voicemaster_name", ",voicemaster_name <name>", "Rename your temporary voice room."),
        ("voicemaster_limit", ",voicemaster_limit <number>", "Set your temporary voice room user limit."),
    ],
    "Special Role": [
        ("shh", ",shh @member", "Toggle the configured special role on or off."),
        ("shh_whitelist_add", ",shh whitelist add @member", "Allow a member to use shh (bot owner only)."),
        ("shh_whitelist_remove", ",shh whitelist remove @member", "Remove shh access (bot owner only)."),
        ("shh_set_role", ",shh set role @role", "Configure the special role (bot owner only)."),
    ],
}


COMMANDS_PER_PAGE = 4


def _help_embed(prefix, category=None, page=0):
    embed = discord.Embed(
        title="ONYX" if category is None else f"ONYX - {category}",
        color=discord.Color.from_rgb(44, 38, 67)
    )

    if category is None:
        embed.description = (
            "Welcome to the help menu\n\n"
            "Select a category below to list commands\n\n"
            f"`{prefix}help <command>` for more information on a specific command"
        )
    else:
        items = HELP_CATEGORIES[category]
        total_pages = max(1, (len(items) + COMMANDS_PER_PAGE - 1) // COMMANDS_PER_PAGE)
        page = max(0, min(page, total_pages - 1))
        start_index = page * COMMANDS_PER_PAGE
        page_items = items[start_index:start_index + COMMANDS_PER_PAGE]

        lines = []
        for index, (command_name, usage, description) in enumerate(page_items, 1):
            display_usage = usage[1:] if usage.startswith(",") else usage
            lines.append(
                f"`{prefix}{display_usage}` — {description or 'No description available.'}"
            )

        embed.description = (
            "\n".join(lines)
            + "\n\n"
            + f"`{prefix}help <command>` for more information on a specific command"
            + (f" · Page {page + 1}/{total_pages}" if total_pages > 1 else "")
        )

    embed.set_footer(text="ONYX • Prefix Commands Only")
    return embed


class HelpCategorySelect(discord.ui.Select):
    def __init__(self, view):
        self.help_view = view
        options = [
            discord.SelectOption(
                label=name,
                description=f"{len(items)} commands",
                value=name
            )
            for name, items in HELP_CATEGORIES.items()
        ]
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


class OnyxHelpView(discord.ui.View):
    def __init__(self, prefix, author_id):
        super().__init__(timeout=180)
        self.prefix = prefix
        self.author_id = author_id
        self.category = None
        self.page = 0

        self.category_select = HelpCategorySelect(self)
        self.add_item(self.category_select)

        # The opening screen intentionally has only the category dropdown.
        self._pagination_added = False

    def _page_count(self):
        if self.category is None:
            return 1
        count = len(HELP_CATEGORIES.get(self.category, []))
        return max(1, (count + COMMANDS_PER_PAGE - 1) // COMMANDS_PER_PAGE)

    def refresh_pagination_controls(self):
        total_pages = self._page_count()

        if total_pages > 1 and not self._pagination_added:
            self.add_item(self.previous_page)
            self.add_item(self.next_page)
            self._pagination_added = True
        elif total_pages <= 1 and self._pagination_added:
            self.remove_item(self.previous_page)
            self.remove_item(self.next_page)
            self._pagination_added = False

        if self._pagination_added:
            self.previous_page.disabled = self.page <= 0
            self.next_page.disabled = self.page >= total_pages - 1

    async def _change_page(self, interaction, direction):
        total_pages = self._page_count()
        new_page = self.page + direction

        if not 0 <= new_page < total_pages:
            return await interaction.response.defer()

        self.page = new_page
        self.refresh_pagination_controls()
        await interaction.response.edit_message(
            embed=_help_embed(self.prefix, self.category, self.page),
            view=self
        )

    @discord.ui.button(
        label="Previous",
        style=discord.ButtonStyle.secondary,
        emoji="◀️",
        row=1
    )
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._change_page(interaction, -1)

    @discord.ui.button(
        label="Next",
        style=discord.ButtonStyle.secondary,
        emoji="▶️",
        row=1
    )
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._change_page(interaction, 1)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
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


async def _send_help(ctx, command_query=None):
    prefix = ctx.prefix

    if command_query:
        query = command_query.strip().lower().replace(" ", "_")
        command = bot.get_command(query)
        if command is None:
            command = bot.get_command(command_query.strip())

        if command is None:
            return await ctx.send(
                f"I couldn't find `{command_query}`. Use `{prefix}help` to browse commands."
            )

        usage = f"{prefix}{command.qualified_name}"
        if command.signature:
            usage += f" {command.signature}"

        embed = discord.Embed(
            title=f"ONYX - {command.qualified_name}",
            description=(
                f"**Usage:** `{usage}`\n"
                f"**Description:** {command.help or command.brief or 'No description available.'}"
            ),
            color=discord.Color.from_rgb(44, 38, 67)
        )
        embed.set_footer(text="ONYX • Prefix Commands Only")
        return await ctx.send(embed=embed)

    view = OnyxHelpView(prefix, ctx.author.id)
    await ctx.send(embed=_help_embed(prefix), view=view)


@bot.command(name="help")
async def prefix_help(ctx, *, command: str = None):
    await _send_help(ctx, command)


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN is missing. "
            "Add it to your environment or .env file."
        )
    bot.run(TOKEN)
