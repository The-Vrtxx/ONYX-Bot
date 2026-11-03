import discord
from discord.ext import commands


class Honeypot(commands.Cog):
    """Creates and monitors a visible honeypot channel."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await self.bot.db.execute(
            """
            CREATE TABLE IF NOT EXISTS onyx_honeypot (
                guild_id BIGINT PRIMARY KEY,
                channel_id BIGINT NOT NULL,
                caught_count BIGINT NOT NULL DEFAULT 0
            )
            """
        )

    async def get_config(self, guild_id):
        return await self.bot.db.fetchone(
            "SELECT channel_id, caught_count FROM onyx_honeypot WHERE guild_id=?",
            (guild_id,)
        )

    @commands.group(name="honeypot", invoke_without_command=True)
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def honeypot(self, ctx):
        await ctx.send(
            f"**Honeypot commands**\n"
            f"`{ctx.prefix}honeypot create` — create the trap channel\n"
            f"`{ctx.prefix}honeypot status` — view its status\n"
            f"`{ctx.prefix}honeypot delete` — remove the channel and disable it"
        )

    @honeypot.command(name="create")
    @commands.has_guild_permissions(manage_guild=True)
    @commands.bot_has_guild_permissions(
        manage_channels=True, manage_messages=True, ban_members=True
    )
    async def create(self, ctx, *, channel_name: str = "dont-type-here"):
        """Create the honeypot channel and enable automatic detection."""
        existing = await self.get_config(ctx.guild.id)
        if existing:
            channel = ctx.guild.get_channel(int(existing["channel_id"]))
            if channel:
                return await ctx.send(
                    f"The honeypot is already active in {channel.mention}. "
                    f"Use `{ctx.prefix}honeypot status` to check it."
                )
            # The old channel was deleted manually; clear the stale setting.
            await self.bot.db.execute(
                "DELETE FROM onyx_honeypot WHERE guild_id=?",
                (ctx.guild.id,)
            )

        safe_name = "-".join(channel_name.lower().split())[:90]
        if not safe_name:
            safe_name = "dont-type-here"

        bot_member = ctx.guild.me
        overwrites = {
            ctx.guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True,
                send_messages=True,
                send_messages_in_threads=False,
                create_public_threads=False,
                create_private_threads=False
            ),
            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True,
                send_messages=True,
                manage_channels=True,
                manage_messages=True,
                ban_members=True,
                embed_links=True
            )
        }

        try:
            channel = await ctx.guild.create_text_channel(
                name=safe_name,
                topic=(
                    "⚠️ DO NOT SEND MESSAGES HERE. This is a security honeypot "
                    "for detecting compromised or automated accounts. "
                    "Messages from non-staff members trigger an automatic ban."
                ),
                overwrites=overwrites,
                reason=f"Honeypot created by {ctx.author} ({ctx.author.id})"
            )
        except discord.Forbidden:
            return await ctx.send(
                "I couldn't create the channel. Check ONYX's Manage Channels permission."
            )
        except discord.HTTPException:
            return await ctx.send("Discord couldn't create the honeypot channel.")

        await self.bot.db.execute(
            """
            INSERT INTO onyx_honeypot (guild_id, channel_id, caught_count)
            VALUES (?, ?, 0)
            ON CONFLICT(guild_id) DO UPDATE SET
                channel_id=excluded.channel_id,
                caught_count=0
            """,
            (ctx.guild.id, channel.id)
        )

        embed = discord.Embed(
            title="⚠️ DO NOT SEND MESSAGES HERE! ⚠️",
            description=(
                "This channel is a trap for compromised accounts.\n"
                "Sending any message here will result in a **ban**.\n\n"
                "🪤 **Accounts Caught:** 0"
            ),
            color=discord.Color.dark_teal()
        )
        embed.set_footer(text="ONYX Security • Honeypot")
        await channel.send(
            embed=embed,
            allowed_mentions=discord.AllowedMentions.none()
        )
        await ctx.send(f"Honeypot created and activated: {channel.mention}")

    @honeypot.command(name="status")
    @commands.has_guild_permissions(manage_guild=True)
    async def status(self, ctx):
        config = await self.get_config(ctx.guild.id)
        if not config:
            return await ctx.send("No honeypot is configured. Use `,honeypot create`.")

        channel = ctx.guild.get_channel(int(config["channel_id"]))
        if channel is None:
            return await ctx.send(
                "The saved honeypot channel no longer exists. "
                "Run `,honeypot create` to replace it."
            )

        embed = discord.Embed(
            title="ONYX Honeypot Status",
            color=discord.Color.dark_teal()
        )
        embed.add_field(name="Channel", value=channel.mention, inline=False)
        embed.add_field(
            name="Accounts caught",
            value=str(config["caught_count"]),
            inline=True
        )
        embed.add_field(name="Protection", value="Active", inline=True)
        await ctx.send(embed=embed)

    @honeypot.command(name="delete")
    @commands.has_guild_permissions(manage_guild=True)
    async def delete(self, ctx):
        config = await self.get_config(ctx.guild.id)
        if not config:
            return await ctx.send("There is no active honeypot to remove.")

        channel = ctx.guild.get_channel(int(config["channel_id"]))
        await self.bot.db.execute(
            "DELETE FROM onyx_honeypot WHERE guild_id=?",
            (ctx.guild.id,)
        )
        if channel:
            try:
                await channel.delete(reason=f"Honeypot removed by {ctx.author}")
            except discord.Forbidden:
                await ctx.send(
                    "Honeypot monitoring is disabled, but I couldn't delete "
                    "the channel. Remove it manually."
                )
                return
            except discord.HTTPException:
                await ctx.send(
                    "Honeypot monitoring is disabled, but Discord couldn't "
                    "delete the channel. Remove it manually."
                )
                return
        await ctx.send("Honeypot disabled and its channel removed, if it existed.")

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot:
            return

        config = await self.get_config(message.guild.id)
        if not config or message.channel.id != int(config["channel_id"]):
            return

        member = message.author
        # Protect the server owner and moderators from accidental messages.
        if (
            member.id == message.guild.owner_id
            or member.guild_permissions.administrator
            or member.guild_permissions.manage_guild
            or member.guild_permissions.manage_messages
        ):
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            return

        try:
            await message.delete()
        except discord.HTTPException:
            pass

        reason = "Posted a message in the server's honeypot channel."
        try:
            await message.guild.ban(
                member,
                reason=reason,
                delete_message_seconds=0
            )
            caught = True
        except (discord.Forbidden, discord.HTTPException):
            caught = False

        if caught:
            await self.bot.db.execute(
                "UPDATE onyx_honeypot SET caught_count=caught_count+1 WHERE guild_id=?",
                (message.guild.id,)
            )

        # Send a concise alert to the configured server log channel, if present.
        settings = await self.bot.db.fetchone(
            "SELECT log_channel_id FROM guild_settings WHERE guild_id=?",
            (message.guild.id,)
        )
        log_channel = None
        if settings and settings["log_channel_id"]:
            log_channel = message.guild.get_channel(int(settings["log_channel_id"]))

        if log_channel:
            embed = discord.Embed(
                title="🪤 Honeypot Triggered",
                description=(
                    f"**Account:** {member} (`{member.id}`)\n"
                    f"**Channel:** {message.channel.mention}\n"
                    f"**Action:** {'Banned' if caught else 'Ban failed — check permissions/role hierarchy'}"
                ),
                color=discord.Color.red() if caught else discord.Color.orange()
            )
            try:
                await log_channel.send(
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions.none()
                )
            except discord.HTTPException:
                pass


async def setup(bot):
    await bot.add_cog(Honeypot(bot))
