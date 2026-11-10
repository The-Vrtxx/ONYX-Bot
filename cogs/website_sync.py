
import logging

from discord.ext import commands

log = logging.getLogger("bot.website_sync")


class WebsiteSync(commands.Cog):
    """Keeps the website informed about servers where ONYX is installed."""

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
        log.info("Website server tracking table is ready.")

    async def sync_guilds(self):
        """Refresh the database with the bot's current server list."""

        guilds = list(self.bot.guilds)

        await self.bot.db.execute(
            "DELETE FROM onyx_bot_guilds"
        )

        for guild in guilds:
            await self.bot.db.execute(
                """
                INSERT INTO onyx_bot_guilds (
                    guild_id,
                    guild_name,
                    updated_at
                )
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(guild_id)
                DO UPDATE SET
                    guild_name = excluded.guild_name,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (guild.id, guild.name)
            )

        log.info(
            "Website server list synchronized: %s servers.",
            len(guilds)
        )

    @commands.Cog.listener()
    async def on_ready(self):
        await self.sync_guilds()

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.bot.db.execute(
            """
            INSERT INTO onyx_bot_guilds (
                guild_id,
                guild_name,
                updated_at
            )
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id)
            DO UPDATE SET
                guild_name = excluded.guild_name,
                updated_at = CURRENT_TIMESTAMP
            """,
            (guild.id, guild.name)
        )

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

        log.info(
            "Removed server from website tracking: %s (%s)",
            guild.name,
            guild.id
        )


async def setup(bot):
    await bot.add_cog(WebsiteSync(bot))
