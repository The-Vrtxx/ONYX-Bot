
"""ONYX background achievement tracker.

No member-facing achievement commands live in Discord.
The website is the member interface for achievements and titles.
"""

from discord.ext import commands

from cogs.achievements.engine import ensure_tables


class Achievements(commands.Cog):
    """Tracks achievement activity silently in the background."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await ensure_tables(self.bot.db)

    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        if ctx.author.bot:
            return

        try:
            from cogs.achievements.engine import record_command
            from cogs.achievements.secrets import secret_event

            await record_command(self.bot, ctx)

            await secret_event(
                self.bot,
                ctx.author,
                "command",
                ctx.guild,
                ctx.command.qualified_name.split()[-1].casefold()
            )

        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "Achievement command tracking failed."
            )

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        try:
            from cogs.achievements.engine import record_message
            from cogs.achievements.secrets import secret_event

            await record_message(self.bot, message)

            await secret_event(
                self.bot,
                message.author,
                "message",
                message.guild
            )

        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "Achievement message tracking failed."
            )


async def setup(bot):
    await bot.add_cog(Achievements(bot))
