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

async def get_prefix(bot, message):
    prefix = ","
    if message.guild is not None and getattr(bot, "db", None) is not None:
        try:
            row = await bot.db.fetchone("SELECT prefix FROM guild_settings WHERE guild_id=?", (message.guild.id,))
            if row and row["prefix"]: prefix = row["prefix"]
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
        await self.db.connect()
        await self.db.initialize()
        for path in sorted(Path("cogs").glob("*.py")):
            if path.name.startswith("_"): continue
            await self.load_extension(f"cogs.{path.stem}")
            log.info("Loaded %s", path.stem)
        # Remove legacy global slash commands published by earlier ONYX versions.
        # The command tree is intentionally left empty; ONYX exposes message-prefix commands only.
        self.tree.clear_commands(guild=None)
        await self.tree.sync()
        log.info("Legacy global application commands cleared; prefix-only command system ready. Database backend: %s", self.db.backend)

    async def close(self):
        await self.db.close()
        await super().close()

bot = CommunityBot()

@bot.event
async def on_ready():
    log.info("Logged in as %s (%s)", bot.user, bot.user.id)
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=",help • your server"))


@bot.event


async def normalize_spaced_command(bot, message):
    """Allow commands such as ',shh whitelist add' for 'shh_whitelist_add'.

    Only the command portion at the beginning of the message is normalized;
    arguments (including multi-word reasons/messages) are left untouched.
    """
    if message.guild is None or message.author.bot:
        return

    prefixes = await get_prefix(bot, message)
    if isinstance(prefixes, str):
        prefixes = [prefixes]

    content = message.content
    matched_prefix = next(
        (prefix for prefix in sorted(prefixes, key=len, reverse=True)
         if content.startswith(prefix)),
        None,
    )
    if not matched_prefix:
        return

    command_text = content[len(matched_prefix):]
    if not command_text:
        return

    # Build aliases from every registered command's full qualified name.
    # Example: shh_whitelist_add -> "shh whitelist add".
    candidates = []
    for command in bot.walk_commands():
        qualified = command.qualified_name
        spaced = qualified.replace("_", " ")
        if spaced != qualified:
            candidates.append((spaced, qualified))

    # Prefer the longest matching command phrase, so 'shh whitelist add'
    # wins over the shorter 'shh'.
    candidates.sort(key=lambda item: len(item[0]), reverse=True)

    lowered = command_text.lower()
    for phrase, registered_name in candidates:
        if lowered == phrase or lowered.startswith(phrase + " "):
            remainder = command_text[len(phrase):]
            message.content = matched_prefix + registered_name + remainder
            return


async def on_message(message):
    # Prefix commands must always be dispatched after message listeners.
    if message.author.bot:
        return
    await normalize_spaced_command(bot, message)
    await bot.process_commands(message)


@bot.event
async def on_command_error(ctx, error):
    # Make command failures visible in Discord and detailed in Render logs.
    original = getattr(error, "original", error)
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.CheckFailure):
        await ctx.send("You need to be the server owner or have Manage Server permission to use this command.")
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"Missing information: `{error.param.name}`. Check `,help` for the command format.")
        return
    if isinstance(error, commands.BadArgument):
        await ctx.send(f"I couldn't understand one of the arguments. Check `,help` for the command format.")
        return
    log.error(
        "Command error in %s from %s (guild=%s): %s",
        ctx.command.qualified_name if ctx.command else "unknown",
        ctx.author.id,
        ctx.guild.id if ctx.guild else "DM",
        repr(original),
        exc_info=(type(original), original, original.__traceback__),
    )
    try:
        await ctx.send("That command ran into an error. The details have been recorded in the Render logs.")
    except discord.HTTPException:
        pass



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
            return await ctx.send(f"Reloaded `{cog}` successfully.")
        except Exception as exc:
            log.exception("Failed to reload extension %s", extension)
            return await ctx.send(
                f"Couldn't reload `{cog}`: `{type(exc).__name__}: {exc}`"
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
        summary += "\\n**Successful:** " + ", ".join(f"`{name}`" for name in succeeded)
    if failed:
        summary += "\\n**Failed:** " + "; ".join(failed)
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
    "Logging": [("logging_set", ",logging set #channel", "Choose the moderation log channel.")],
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
        ("embed_template_delete", ",embed template delete <name>", "Delete an embed template."),
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
    "Special Role": [
        ("shh", ",shh @member", "Toggle the configured special role on or off."),
        ("shh_whitelist_add", ",shh whitelist add @member", "Allow a member to use shh (bot owner only)."),
        ("shh_whitelist_remove", ",shh whitelist remove @member", "Remove shh access (bot owner only)."),
        ("shh_set_role", ",shh set role @role", "Configure the special role (bot owner only)."),
    ],
}


def _help_embed(prefix, category=None, command=None):
    embed = discord.Embed(
        title="ONYX • Help Center",
        description=(
            f"Browse commands by category using the menus below.\n"
            f"**Current prefix:** `{prefix}`  •  **Prefix commands only**\n"
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
            await interaction.response.send_message("This help menu belongs to the person who opened it. Use `,help` to open your own.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


async def _send_help(ctx):
    prefix = ctx.prefix
    view = OnyxHelpView(prefix, ctx.author.id)
    await ctx.send(embed=_help_embed(prefix), view=view)

@bot.command(name="help")
async def prefix_help(ctx):
    await _send_help(ctx)

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN is missing. Add it to your environment or .env file.")
    bot.run(TOKEN)
