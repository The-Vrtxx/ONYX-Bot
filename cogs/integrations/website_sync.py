
import json
import logging
import re

from discord.ext import commands

log = logging.getLogger("bot.website_sync")


HELP_FOLDER_LABELS = {
    "administration": "Administration",
    "community": "Community",
    "core": "Utilities & Integrations",
    "integrations": "Utilities & Integrations",
    "leveling": "Leveling & Progression",
    "logging": "Logging & Audit",
    "moderation": "Moderation",
    "security": "Security",
    "server": "Server Management",
    "support": "Support",
    "voice": "Utilities & Integrations",
}

HELP_MODULE_OVERRIDES = {
    "automod": "Moderation",
}


def is_owner_restricted(command):
    """Detect owner-only checks on a command or any parent group."""
    current = command

    while current is not None:
        for check in getattr(current, "checks", []):
            check_name = getattr(check, "__qualname__", "")
            if "is_owner" in check_name.casefold():
                return True

        current = getattr(current, "parent", None)

    # Some owner-only commands use documentation instead of the
    # built-in is_owner decorator. Keep those out of the public directory.
    description = " ".join(
        str(value or "")
        for value in (
            getattr(command, "help", None),
            getattr(command, "brief", None),
        )
    )

    if re.search(
        r"\bowner[- ]only\b|\(owner\)",
        description,
        flags=re.IGNORECASE,
    ):
        return True

    return False


class WebsiteSync(commands.Cog):
    """Synchronizes ONYX server, member, and command information with the website."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_bot_guilds (
                guild_id BIGINT PRIMARY KEY,
                guild_name TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_command_catalog (
                command_name TEXT PRIMARY KEY,
                usage TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                aliases TEXT NOT NULL DEFAULT '[]',
                cog_name TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_bot_stats (
                id INTEGER PRIMARY KEY,
                guild_count BIGINT NOT NULL DEFAULT 0,
                member_count BIGINT NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        log.info("Website synchronization tables are ready.")

    async def sync_guilds(self):
        guilds = list(self.bot.guilds)

        await self.bot.db.execute("DELETE FROM onyx_bot_guilds")

        for guild in guilds:
            await self.bot.db.execute(
                """
                INSERT INTO onyx_bot_guilds (
                    guild_id, guild_name, updated_at
                )
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(guild_id)
                DO UPDATE SET
                    guild_name = excluded.guild_name,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (guild.id, guild.name)
            )

        log.info("Website server list synchronized: %s servers.", len(guilds))

    async def sync_stats(self):
        guilds = list(self.bot.guilds)
        guild_count = len(guilds)
        member_count = sum(int(guild.member_count or 0) for guild in guilds)

        await self.bot.db.execute(
            """
            INSERT INTO onyx_bot_stats (
                id, guild_count, member_count, updated_at
            )
            VALUES (1, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id)
            DO UPDATE SET
                guild_count = excluded.guild_count,
                member_count = excluded.member_count,
                updated_at = CURRENT_TIMESTAMP
            """,
            (guild_count, member_count)
        )

        log.info(
            "Website statistics synchronized: %s servers, %s combined members.",
            guild_count,
            member_count
        )

    def build_command_catalog(self):
        """Build a catalog containing only publicly usable commands."""
        catalog = []
        excluded = []

        for command in self.bot.walk_commands():
            if command.hidden or is_owner_restricted(command):
                excluded.append(command.qualified_name)
                continue

            if command.cog:
                module_parts = command.cog.__class__.__module__.split(".")
                module = module_parts[-1]
                folder = module_parts[-2] if len(module_parts) >= 2 else "core"

                category = HELP_MODULE_OVERRIDES.get(
                    module,
                    HELP_FOLDER_LABELS.get(folder, "Other")
                )
            else:
                module = "core"
                category = "Utilities & Integrations"

            usage = f",{command.qualified_name}"

            if command.signature:
                usage += f" {command.signature}"

            catalog.append({
                "command_name": command.qualified_name,
                "usage": usage,
                "category": category,
                "description": (
                    command.help
                    or command.brief
                    or "No description available."
                ),
                "aliases": json.dumps(
                    list(command.aliases),
                    ensure_ascii=False
                ),
                "cog_name": module,
            })

        catalog.sort(
            key=lambda item: (
                item["category"].casefold(),
                item["command_name"].casefold()
            )
        )

        log.info(
            "Command catalog built: %s public commands; %s private commands excluded.",
            len(catalog),
            len(excluded)
        )

        if excluded:
            log.debug(
                "Excluded private commands: %s",
                ", ".join(sorted(excluded))
            )

        return catalog

    async def sync_commands(self):
        """Replace the website catalog with currently loaded public commands."""
        catalog = self.build_command_catalog()

        await self.bot.db.execute("DELETE FROM onyx_command_catalog")

        for command in catalog:
            await self.bot.db.execute(
                """
                INSERT INTO onyx_command_catalog (
                    command_name,
                    usage,
                    category,
                    description,
                    aliases,
                    cog_name,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(command_name)
                DO UPDATE SET
                    usage = excluded.usage,
                    category = excluded.category,
                    description = excluded.description,
                    aliases = excluded.aliases,
                    cog_name = excluded.cog_name,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    command["command_name"],
                    command["usage"],
                    command["category"],
                    command["description"],
                    command["aliases"],
                    command["cog_name"],
                )
            )

        log.info(
            "Website command catalog synchronized: %s public commands.",
            len(catalog)
        )

    async def sync_all(self):
        await self.sync_guilds()
        await self.sync_commands()
        await self.sync_stats()

    @commands.Cog.listener()
    async def on_ready(self):
        await self.sync_all()

    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        """Refresh the website whenever the owner reloads cogs."""
        if not ctx.command:
            return

        if ctx.command.qualified_name != "reload":
            return

        try:
            await self.sync_commands()
            log.info("Website command catalog refreshed after cog reload.")
        except Exception:
            log.exception("Website command catalog refresh failed after cog reload.")

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.bot.db.execute(
            """
            INSERT INTO onyx_bot_guilds (
                guild_id, guild_name, updated_at
            )
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id)
            DO UPDATE SET
                guild_name = excluded.guild_name,
                updated_at = CURRENT_TIMESTAMP
            """,
            (guild.id, guild.name)
        )

        await self.sync_stats()

        log.info(
            "Added server to website tracking: %s (%s)",
            guild.name,
            guild.id
        )

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        await self.bot.db.execute(
            "DELETE FROM onyx_bot_guilds WHERE guild_id = ?",
            (guild.id,)
        )

        await self.sync_stats()

        log.info(
            "Removed server from website tracking: %s (%s)",
            guild.name,
            guild.id
        )

    @commands.Cog.listener()
    async def on_member_join(self, member):
        await self.sync_stats()

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        await self.sync_stats()


async def setup(bot):
    await bot.add_cog(WebsiteSync(bot))
