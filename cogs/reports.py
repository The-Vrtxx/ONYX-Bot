import discord
from discord.ext import commands


class Reports(commands.Cog):
    """Per-server member reports with sequential ticket numbers and attachment links."""

    MAX_ATTACHMENTS = 10
    MAX_DETAILS = 3500

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await self.bot.db.execute(
            """
            CREATE TABLE IF NOT EXISTS onyx_report_settings (
                guild_id BIGINT PRIMARY KEY,
                channel_id BIGINT NOT NULL
            )
            """
        )
        await self.bot.db.execute(
            """
            CREATE TABLE IF NOT EXISTS onyx_report_counters (
                guild_id BIGINT PRIMARY KEY,
                next_ticket BIGINT NOT NULL DEFAULT 0
            )
            """
        )

    @commands.command(
        name="setupreport",
        help="Set the channel where member reports are delivered."
    )
    @commands.guild_only()
    @commands.is_owner()
    @commands.bot_has_guild_permissions(send_messages=True, embed_links=True)
    async def setup_report(self, ctx, channel: discord.TextChannel):
        me = ctx.guild.me
        permissions = channel.permissions_for(me)
        if not permissions.view_channel or not permissions.send_messages or not permissions.embed_links:
            return await ctx.send(
                "I need **View Channel**, **Send Messages**, and **Embed Links** in that channel."
            )

        await self.bot.db.execute(
            """
            INSERT INTO onyx_report_settings (guild_id, channel_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id
            """,
            (ctx.guild.id, channel.id)
        )
        await ctx.send(f"Reports for **{ctx.guild.name}** will be sent to {channel.mention}.")

    async def next_ticket_number(self, guild_id):
        # Atomic per-server increment. RETURNING is supported by PostgreSQL and modern SQLite.
        row = await self.bot.db.fetchone(
            """
            INSERT INTO onyx_report_counters (guild_id, next_ticket)
            VALUES (?, 1)
            ON CONFLICT(guild_id) DO UPDATE
                SET next_ticket = onyx_report_counters.next_ticket + 1
            RETURNING next_ticket
            """,
            (guild_id,)
        )
        return int(row["next_ticket"])

    @commands.command(
        name="report",
        help="Submit a report to this server's configured report channel. You can attach images."
    )
    @commands.guild_only()
    async def report(self, ctx, *, details: str = ""):
        config = await self.bot.db.fetchone(
            "SELECT channel_id FROM onyx_report_settings WHERE guild_id=?",
            (ctx.guild.id,)
        )
        if not config:
            return await ctx.send(
                "The report system hasn't been set up in this server yet. Ask a server administrator to run `,setupreport #channel`."
            )

        report_channel = ctx.guild.get_channel(int(config["channel_id"]))
        if not isinstance(report_channel, discord.TextChannel):
            return await ctx.send(
                "The configured report channel is missing. Ask an administrator to run `,setupreport #channel` again."
            )

        attachments = list(ctx.message.attachments)
        if not details.strip() and not attachments:
            return await ctx.send(
                "Please include a description, an attachment, or both. Example: `,report I need to report an issue...`"
            )
        if len(attachments) > self.MAX_ATTACHMENTS:
            return await ctx.send(f"Please submit no more than {self.MAX_ATTACHMENTS} attachments in one report.")

        details = details.strip() or "No written description was provided."
        if len(details) > self.MAX_DETAILS:
            return await ctx.send(f"Please keep the report description under {self.MAX_DETAILS} characters.")

        permissions = report_channel.permissions_for(ctx.guild.me)
        if not permissions.view_channel or not permissions.send_messages or not permissions.embed_links:
            return await ctx.send(
                "I can't post in the configured report channel. Ask an administrator to check my channel permissions."
            )

        try:
            ticket_number = await self.next_ticket_number(ctx.guild.id)
        except Exception:
            return await ctx.send("I couldn't assign a ticket number right now. Please try again shortly.")

        embed = discord.Embed(
            title=f"New Member Report • #{ticket_number:04d}",
            description=details,
            color=discord.Color.dark_teal(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(
            name="Submitted by",
            value=f"{ctx.author.mention}\n`{ctx.author}` (`{ctx.author.id}`)",
            inline=True
        )
        embed.add_field(
            name="Server",
            value=f"{ctx.guild.name}\n`{ctx.guild.id}`",
            inline=True
        )
        embed.add_field(name="Ticket", value=f"`#{ticket_number:04d}`", inline=True)

        if attachments:
            attachment_lines = []
            for index, attachment in enumerate(attachments, start=1):
                safe_name = discord.utils.escape_markdown(attachment.filename)
                attachment_lines.append(f"[{index}. {safe_name}]({attachment.url})")
            embed.add_field(
                name=f"Attachments ({len(attachments)})",
                value="\n".join(attachment_lines)[:1024],
                inline=False
            )

        try:
            await report_channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none()
            )
        except discord.Forbidden:
            return await ctx.send(
                "I couldn't send your report. Please let a server administrator know the report channel permissions need fixing."
            )
        except discord.HTTPException:
            return await ctx.send(
                "Discord couldn't deliver your report right now. Please try again shortly."
            )

        await ctx.send(
            f"Your report was submitted successfully. Your ticket number is **#{ticket_number:04d}**.",
            delete_after=20
        )


async def setup(bot):
    await bot.add_cog(Reports(bot))
