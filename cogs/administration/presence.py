import discord
from discord.ext import commands, tasks


class Presence(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.rotate_presence.is_running():
            self.rotate_presence.start()

    @tasks.loop(seconds=30)
    async def rotate_presence(self):
        server_count = len(self.bot.guilds)
        # Combined member count across servers, not unique users.
        member_count = sum(guild.member_count or 0 for guild in self.bot.guilds)

        activity_text = (
            f"your server. your command. | "
            f"{server_count:,} servers • {member_count:,} members"
        )

        await self.bot.change_presence(
            status=discord.Status.online,
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=activity_text
            )
        )

    @rotate_presence.before_loop
    async def before_rotate_presence(self):
        await self.bot.wait_until_ready()

    def cog_unload(self):
        self.rotate_presence.cancel()


async def setup(bot):
    await bot.add_cog(Presence(bot))
