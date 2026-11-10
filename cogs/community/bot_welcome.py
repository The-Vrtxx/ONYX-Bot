import logging

import discord
from discord.ext import commands

logger = logging.getLogger(__name__)

SUPPORT_SERVER_URL = "https://discord.gg/7pBxx2XjEd"


class BotWelcome(commands.Cog):
    """Welcome the server owner and announce ONYX in the server when it joins."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def build_welcome_embed(self, guild: discord.Guild) -> discord.Embed:
        embed = discord.Embed(
            title="ONYX has arrived.",
            description=(
                f"Thanks for adding **ONYX** to **{discord.utils.escape_markdown(guild.name)}**!\n\n"
                "Your server is ready for a sharper, cleaner way to manage your community.\n\n"
                "**New to ONYX?** Start with `,help` to see the available commands "
                "and learn what the bot can do."
            ),
            color=discord.Color.from_rgb(42, 45, 54),
        )
        embed.add_field(
            name="Quick start",
            value="Type `,help` in your server to explore ONYX's commands.",
            inline=False,
        )
        embed.add_field(
            name="Need a hand?",
            value="Join the ONYX support server for help and updates.",
            inline=False,
        )
        embed.set_footer(text="ONYX • Built for your community")

        if self.bot.user:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        return embed

    def build_support_view(self) -> discord.ui.View:
        view = discord.ui.View()
        view.add_item(
            discord.ui.Button(
                label="Join ONYX Support",
                style=discord.ButtonStyle.link,
                url=SUPPORT_SERVER_URL,
                emoji="🛠️",
            )
        )
        return view

    async def find_main_channel(self, guild: discord.Guild):
        """Prefer the configured system channel, then #general, then first sendable text channel."""
        me = guild.me
        if me is None:
            return None

        candidates = []

        if guild.system_channel is not None:
            candidates.append(guild.system_channel)

        general_channels = [
            channel for channel in guild.text_channels
            if channel.name.lower() in {"general", "main", "main-chat", "main_chat"}
        ]
        candidates.extend(channel for channel in general_channels if channel not in candidates)
        candidates.extend(channel for channel in guild.text_channels if channel not in candidates)

        for channel in candidates:
            permissions = channel.permissions_for(me)
            if permissions.view_channel and permissions.send_messages and permissions.embed_links:
                return channel

        return None

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        embed = self.build_welcome_embed(guild)
        view = self.build_support_view()

        # Post in the server's system channel, #general, or first suitable text channel.
        channel = await self.find_main_channel(guild)
        if channel is not None:
            try:
                await channel.send(embed=embed, view=view)
                logger.info(
                    "Posted ONYX welcome message in #%s for guild %s (%s).",
                    channel.name,
                    guild.name,
                    guild.id,
                )
            except discord.HTTPException:
                logger.exception(
                    "Could not post ONYX welcome message in guild %s (%s).",
                    guild.name,
                    guild.id,
                )
        else:
            logger.warning(
                "ONYX joined guild %s (%s), but no suitable text channel was available.",
                guild.name,
                guild.id,
            )

        # Also DM the server owner when possible.
        owner = guild.owner
        if owner is None and guild.owner_id:
            try:
                owner = await guild.fetch_member(guild.owner_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logger.warning(
                    "ONYX joined guild %s, but could not fetch its owner.",
                    guild.id,
                )
                return

        if owner is None:
            logger.warning("ONYX joined guild %s, but its owner was unavailable.", guild.id)
            return

        try:
            await owner.send(embed=embed, view=view)
            logger.info("Sent ONYX welcome DM for guild %s (%s).", guild.name, guild.id)
        except discord.Forbidden:
            logger.info(
                "Could not DM the owner of guild %s (%s); their DMs may be closed.",
                guild.name,
                guild.id,
            )
        except discord.HTTPException:
            logger.exception(
                "Discord error while sending ONYX welcome DM for guild %s (%s).",
                guild.name,
                guild.id,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(BotWelcome(bot))
