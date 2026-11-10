"""Publishes per-server counts and role metadata for the ONYX web dashboard."""
import asyncio
import logging
from discord.ext import commands, tasks

log = logging.getLogger("bot.dashboard_sync")


class DashboardSync(commands.Cog):
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
            CREATE TABLE IF NOT EXISTS onyx_bot_roles (
                guild_id BIGINT NOT NULL, role_id BIGINT NOT NULL,
                role_name TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0,
                managed INTEGER NOT NULL DEFAULT 0, is_default INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, role_id)
            )
        """)
        # The website API applies the same additive columns on its own startup.
        for sql in (
            "ALTER TABLE onyx_bot_guilds ADD COLUMN IF NOT EXISTS member_count BIGINT NOT NULL DEFAULT 0",
            "ALTER TABLE onyx_bot_guilds ADD COLUMN IF NOT EXISTS channel_count INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE onyx_bot_guilds ADD COLUMN IF NOT EXISTS role_count INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE onyx_bot_guilds ADD COLUMN IF NOT EXISTS bot_top_role_position INTEGER NOT NULL DEFAULT 0",
        ):
            try:
                await self.bot.db.execute(sql)
            except Exception:
                # The API performs the migration for PostgreSQL. Older SQLite installs
                # can still use the dashboard's moderation and analytics modules.
                log.debug("Could not apply dashboard snapshot migration", exc_info=True)

    async def sync_guild(self, guild):
        me = guild.me
        top_position = me.top_role.position if me and me.top_role else 0
        await self.bot.db.execute("""
            INSERT INTO onyx_bot_guilds (
                guild_id,guild_name,member_count,channel_count,role_count,
                bot_top_role_position,updated_at
            ) VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id) DO UPDATE SET
                guild_name=excluded.guild_name,
                member_count=excluded.member_count,
                channel_count=excluded.channel_count,
                role_count=excluded.role_count,
                bot_top_role_position=excluded.bot_top_role_position,
                updated_at=CURRENT_TIMESTAMP
        """, (guild.id, guild.name, int(guild.member_count or 0), len(guild.channels), len(guild.roles), top_position))

        await self.bot.db.execute("DELETE FROM onyx_bot_roles WHERE guild_id=?", (guild.id,))
        for role in guild.roles:
            await self.bot.db.execute("""
                INSERT INTO onyx_bot_roles(guild_id,role_id,role_name,position,managed,is_default,updated_at)
                VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(guild_id,role_id) DO UPDATE SET
                    role_name=excluded.role_name,position=excluded.position,
                    managed=excluded.managed,is_default=excluded.is_default,updated_at=CURRENT_TIMESTAMP
            """, (guild.id, role.id, role.name, role.position, int(role.managed), int(role.is_default())))

    async def sync_all(self):
        for guild in list(self.bot.guilds):
            try:
                await self.sync_guild(guild)
            except Exception:
                log.exception("Could not synchronize dashboard data for guild %s", guild.id)

    @tasks.loop(minutes=5)
    async def refresh_snapshots(self):
        await self.sync_all()

    @refresh_snapshots.before_loop
    async def before_refresh(self):
        await self.bot.wait_until_ready()

    async def delayed_initial_sync(self):
        # Let the existing WebsiteSync cog finish its startup snapshot first.
        await asyncio.sleep(5)
        await self.sync_all()

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.refresh_snapshots.is_running():
            self.refresh_snapshots.start()
        asyncio.create_task(self.delayed_initial_sync())

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.sync_guild(guild)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        await self.bot.db.execute("DELETE FROM onyx_bot_guilds WHERE guild_id=?", (guild.id,))
        await self.bot.db.execute("DELETE FROM onyx_bot_roles WHERE guild_id=?", (guild.id,))

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        await self.sync_guild(role.guild)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        await self.sync_guild(role.guild)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        await self.sync_guild(after.guild)


async def setup(bot):
    await bot.add_cog(DashboardSync(bot))
