
import json
import logging

from discord.ext import commands, tasks

log = logging.getLogger("onyx.health")


class HealthReporter(commands.Cog):
    """Publishes ONYX bot runtime health to the shared database."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await self.bot.db.execute(
            """
            CREATE TABLE IF NOT EXISTS onyx_bot_runtime_health (
                id INTEGER PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'starting',
                database_status TEXT NOT NULL DEFAULT 'unknown',
                uptime_seconds BIGINT NOT NULL DEFAULT 0,
                guild_count BIGINT NOT NULL DEFAULT 0,
                member_count BIGINT NOT NULL DEFAULT 0,
                loaded_cogs TEXT NOT NULL DEFAULT '[]',
                discovered_cogs TEXT NOT NULL DEFAULT '[]',
                failed_cogs TEXT NOT NULL DEFAULT '[]',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # Safely add the new fields to existing installations.
        if self.bot.db.backend == "postgres":
            await self.bot.db.execute(
                """
                ALTER TABLE onyx_bot_runtime_health
                ADD COLUMN IF NOT EXISTS discovered_cogs TEXT NOT NULL DEFAULT '[]'
                """
            )
            await self.bot.db.execute(
                """
                ALTER TABLE onyx_bot_runtime_health
                ADD COLUMN IF NOT EXISTS failed_cogs TEXT NOT NULL DEFAULT '[]'
                """
            )
        else:
            columns = await self.bot.db.fetchall(
                "PRAGMA table_info(onyx_bot_runtime_health)"
            )
            column_names = {column["name"] for column in columns}

            if "discovered_cogs" not in column_names:
                await self.bot.db.execute(
                    """
                    ALTER TABLE onyx_bot_runtime_health
                    ADD COLUMN discovered_cogs TEXT NOT NULL DEFAULT '[]'
                    """
                )

            if "failed_cogs" not in column_names:
                await self.bot.db.execute(
                    """
                    ALTER TABLE onyx_bot_runtime_health
                    ADD COLUMN failed_cogs TEXT NOT NULL DEFAULT '[]'
                    """
                )

        self.publish_health.start()

    async def cog_unload(self):
        self.publish_health.cancel()

    @tasks.loop(seconds=30)
    async def publish_health(self):
        try:
            # Verify the bot's database connection.
            await self.bot.db.fetchone("SELECT 1 AS health_check")
            database_status = "connected"

            # Calculate actual bot uptime.
            current_time = self.bot.loop.time()
            start_timestamp = getattr(
                self.bot,
                "_health_start_monotonic",
                None
            )

            if start_timestamp is None:
                self.bot._health_start_monotonic = current_time
                uptime_seconds = 0
            else:
                uptime_seconds = max(
                    0,
                    int(current_time - start_timestamp)
                )

            # Read the extension inventory recorded during startup.
            discovered_cogs = sorted(
                getattr(self.bot, "discovered_cogs", [])
            )

            failed_cogs = getattr(
                self.bot,
                "failed_cogs",
                []
            )

            # Always use Discord.py's live extension registry
            # for the successfully loaded list.
            loaded_cogs = sorted(
                extension.removeprefix("cogs.")
                for extension in self.bot.extensions.keys()
            )

            # Count actual guilds and cached members.
            guild_count = len(self.bot.guilds)

            member_count = sum(
                guild.member_count or len(guild.members)
                for guild in self.bot.guilds
            )

            await self.bot.db.execute(
                """
                INSERT INTO onyx_bot_runtime_health (
                    id,
                    status,
                    database_status,
                    uptime_seconds,
                    guild_count,
                    member_count,
                    loaded_cogs,
                    discovered_cogs,
                    failed_cogs,
                    updated_at
                )
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    database_status=excluded.database_status,
                    uptime_seconds=excluded.uptime_seconds,
                    guild_count=excluded.guild_count,
                    member_count=excluded.member_count,
                    loaded_cogs=excluded.loaded_cogs,
                    discovered_cogs=excluded.discovered_cogs,
                    failed_cogs=excluded.failed_cogs,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    "online",
                    database_status,
                    uptime_seconds,
                    guild_count,
                    member_count,
                    json.dumps(loaded_cogs),
                    json.dumps(discovered_cogs),
                    json.dumps(failed_cogs)
                )
            )

        except Exception:
            log.exception("Could not publish ONYX runtime health.")

    @publish_health.before_loop
    async def before_publish_health(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self):
        log.info(
            "ONYX Health Reporter active. Monitoring %s guilds.",
            len(self.bot.guilds)
        )


async def setup(bot):
    await bot.add_cog(HealthReporter(bot))
