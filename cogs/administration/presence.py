
import logging

import discord
from discord.ext import commands, tasks


log = logging.getLogger("onyx.presence")


class Presence(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.rotate_presence.is_running():
            self.rotate_presence.start()

    async def load_settings(self):
        """Load global presence settings from the shared PostgreSQL database."""
        try:
            row = await self.bot.db.fetchone("""
                SELECT presence_status, activity_type, activity_text
                FROM onyx_global_system_settings
                WHERE id=1
            """)

            if not row:
                return None

            return row

        except Exception:
            log.exception("Could not load global presence settings.")
            return None

    @tasks.loop(seconds=30)
    async def rotate_presence(self):
        settings = await self.load_settings()

        if not settings:
            return

        status_name = str(settings["presence_status"]).lower()
        activity_name = str(settings["activity_type"]).lower()
        activity_text = str(settings["activity_text"]).strip()

        status_map = {
            "online": discord.Status.online,
            "idle": discord.Status.idle,
            "dnd": discord.Status.dnd,
            "invisible": discord.Status.invisible,
        }

        activity_map = {
            "playing": discord.ActivityType.playing,
            "watching": discord.ActivityType.watching,
            "listening": discord.ActivityType.listening,
            "competing": discord.ActivityType.competing,
        }

        status = status_map.get(status_name, discord.Status.online)
        activity_type = activity_map.get(
            activity_name,
            discord.ActivityType.watching
        )

        if not activity_text:
            activity_text = "your server. your command."

        try:
            await self.bot.change_presence(
                status=status,
                activity=discord.Activity(
                    type=activity_type,
                    name=activity_text[:128]
                )
            )

            log.info(
                "Applied global presence settings: status=%s activity=%s text=%s",
                status_name,
                activity_name,
                activity_text
            )

        except discord.HTTPException:
            log.exception("Discord rejected the presence update.")

    @rotate_presence.before_loop
    async def before_rotate_presence(self):
        await self.bot.wait_until_ready()

    def cog_unload(self):
        self.rotate_presence.cancel()


async def setup(bot):
    await bot.add_cog(Presence(bot))
