import json
import logging

from discord.ext import commands

log = logging.getLogger("bot.website_sync")


# Kept as a fallback for cogs that are not inside one of the main folders.
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
    "reports": "Reports",
}


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

        # Public website statistics. One row stores the latest totals.
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
        """Refresh the database with the bot's current server list."""
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
        """Publish server count and combined member count to the website."""
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
        """Build a catalog from commands currently loaded by Discord.py."""
        catalog = []

        for command in self.bot.walk_commands():
            if command.hidden:
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
                "aliases": json.dumps(list(command.aliases), ensure_ascii=False),
                "cog_name": module,
            })

        catalog.sort(
            key=lambda item: (
                item["category"].casefold(),
                item["command_name"].casefold()
            )
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
                    command_name, usage, category, description,
                    aliases, cog_name, updated_at
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
        log.info("Added server to website tracking: %s (%s)", guild.name, guild.id)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        await self.bot.db.execute(
            "DELETE FROM onyx_bot_guilds WHERE guild_id = ?",
            (guild.id,)
        )
        await self.sync_stats()
        log.info("Removed server from website tracking: %s (%s)", guild.name, guild.id)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        await self.sync_stats()

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        await self.sync_stats()


async def setup(bot):
    await bot.add_cog(WebsiteSync(bot))
