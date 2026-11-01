import re
from collections import defaultdict, deque
from time import monotonic
import discord
from discord import app_commands
from discord.ext import commands

class AutoMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.recent = defaultdict(deque)

    @app_commands.command(name="automod", description="Configure automatic moderation.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def automod(self, interaction: discord.Interaction, enabled: bool, block_invites: bool = True, block_links: bool = False, spam_limit: app_commands.Range[int, 3, 10] = 5):
        await self.bot.db.execute(
            """INSERT INTO guild_settings (guild_id,automod_enabled,block_invites,block_links,spam_limit)
            VALUES (?,?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET
            automod_enabled=excluded.automod_enabled, block_invites=excluded.block_invites,
            block_links=excluded.block_links, spam_limit=excluded.spam_limit""",
            (interaction.guild.id, int(enabled), int(block_invites), int(block_links), spam_limit))
        await interaction.response.send_message(
            f"Automod **{'enabled' if enabled else 'disabled'}**. Invite filter: {block_invites}; link filter: {block_links}; spam threshold: {spam_limit}.",
            ephemeral=True)

    @app_commands.command(name="automod_ignore", description="Ignore a channel in automod.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ignore(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await self.bot.db.execute("INSERT INTO automod_ignored VALUES (?,?) ON CONFLICT DO NOTHING", (interaction.guild.id, channel.id))
        await interaction.response.send_message(f"Automod will ignore {channel.mention}.", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot:
            return
        if message.author.guild_permissions.manage_messages:
            return
        settings = await self.bot.db.fetchone("SELECT * FROM guild_settings WHERE guild_id=?", (message.guild.id,))
        if not settings or not settings["automod_enabled"]:
            return
        ignored = await self.bot.db.fetchone("SELECT 1 FROM automod_ignored WHERE guild_id=? AND channel_id=?", (message.guild.id, message.channel.id))
        if ignored:
            return
        reason = None
        content = message.content.lower()
        if settings["block_invites"] and re.search(r"(discord\.gg/|discord(app)?\.com/invite/)", content):
            reason = "Discord invite link"
        elif settings["block_links"] and re.search(r"https?://", content):
            reason = "Link filter"
        else:
            now = monotonic()
            bucket = self.recent[(message.guild.id, message.author.id)]
            bucket.append(now)
            while bucket and now - bucket[0] > 7:
                bucket.popleft()
            if len(bucket) >= settings["spam_limit"]:
                reason = "Message spam"
                bucket.clear()
        if reason:
            try:
                await message.delete()
                await message.channel.send(f"{message.author.mention}, your message was removed: **{reason}**.", delete_after=5)
            except discord.Forbidden:
                pass

async def setup(bot): await bot.add_cog(AutoMod(bot))
