import discord
from discord.ext import commands


class Reports(commands.Cog):
    """Per-server reports with optional forwarding to one owner-configured central channel."""

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
        await self.bot.db.execute(
            """
            CREATE TABLE IF NOT EXISTS onyx_central_report_settings (
                id BIGINT PRIMARY KEY,
                channel_id BIGINT NOT NULL
            )
            """
        )
        await self.bot.db.execute(
            """
            CREATE TABLE IF NOT EXISTS onyx_central_report_counter (
                id BIGINT PRIMARY KEY,
                next_ticket BIGINT NOT NULL DEFAULT 0
            )
            """
        )

    async def _check_channel(self, channel, guild):
        if not isinstance(channel, discord.TextChannel):
            return False
        permissions = channel.permissions_for(guild.me)
        return bool(
            permissions.view_channel
            and permissions.send_messages
            and permissions.embed_links
        )

    @commands.command(
        name="setupreport",
        help="(Owner) Set the report channel for the current server."
    )
    @commands.guild_only()
    @commands.is_owner()
    async def setup_report(self, ctx, channel: discord.TextChannel):
        if not await self._check_channel(channel, ctx.guild):
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
        await ctx.send(f"Local reports for **{ctx.guild.name}** will be sent to {channel.mention}.")

    @commands.command(
        name="setupcentralreports",
        aliases=["centralreports"],
        help="(Owner only) Set the one central channel that receives reports from every server."
    )
    @commands.guild_only()
    @commands.is_owner()
    async def setup_central_reports(self, ctx, channel: discord.TextChannel):
        if not await self._check_channel(channel, ctx.guild):
            return await ctx.send(
                "I need **View Channel**, **Send Messages**, and **Embed Links** in that channel."
            )

        await self.bot.db.execute(
            """
            INSERT INTO onyx_central_report_settings (id, channel_id)
            VALUES (1, ?)
            ON CONFLICT(id) DO UPDATE SET channel_id=excluded.channel_id
            """,
            (channel.id,)
        )
        await ctx.send(
            f"Central reporting is now enabled. Reports from every server will be forwarded to {channel.mention}."
        )

    async def next_server_ticket_number(self, guild_id):
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

    async def next_central_ticket_number(self):
        row = await self.bot.db.fetchone(
            """
            INSERT INTO onyx_central_report_counter (id, next_ticket)
            VALUES (1, 1)
            ON CONFLICT(id) DO UPDATE
                SET next_ticket = onyx_central_report_counter.next_ticket + 1
            RETURNING next_ticket
            """,
            ()
        )
        return int(row["next_ticket"])

    @commands.command(
        name="report",
        help="Submit a report. It is forwarded to the central ONYX report channel and this server's local channel, if configured."
    )
    @commands.guild_only()
    async def report(self, ctx, *, details: str = ""):
        local_config = await self.bot.db.fetchone(
            "SELECT channel_id FROM onyx_report_settings WHERE guild_id=?",
            (ctx.guild.id,)
        )
        central_config = await self.bot.db.fetchone(
            "SELECT channel_id FROM onyx_central_report_settings WHERE id=1",
            ()
        )

        if not local_config and not central_config:
            return await ctx.send(
                "The report system isn't configured yet. Please contact a server administrator."
            )

        local_channel = None
        if local_config:
            local_channel = ctx.guild.get_channel(int(local_config["channel_id"]))
            if not isinstance(local_channel, discord.TextChannel):
                local_channel = None

        central_channel = None
        if central_config:
            central_channel = self.bot.get_channel(int(central_config["channel_id"]))
            if not isinstance(central_channel, discord.TextChannel):
                try:
                    central_channel = await self.bot.fetch_channel(int(central_config["channel_id"]))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    central_channel = None

        if local_channel is None and central_channel is None:
            return await ctx.send(
                "The configured report channel couldn't be found. Please contact the ONYX owner."
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

        local_number = None
        central_number = None
        try:
            if local_channel is not None:
                local_number = await self.next_server_ticket_number(ctx.guild.id)
            if central_channel is not None:
                central_number = await self.next_central_ticket_number()
        except Exception:
            return await ctx.send("I couldn't assign a report number right now. Please try again shortly.")

        embed = discord.Embed(
            title="New Member Report",
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
        if local_number is not None:
            embed.add_field(name="Server report #", value=f"`#{local_number:04d}`", inline=True)
        if central_number is not None:
            embed.add_field(name="Central report #", value=f"`#{central_number:05d}`", inline=True)

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

        sent_local = False
        sent_central = False

        if local_channel is not None:
            local_embed = embed.copy()
            local_embed.title = f"New Member Report • #{local_number:04d}"
            try:
                await local_channel.send(
                    embed=local_embed,
                    allowed_mentions=discord.AllowedMentions.none()
                )
                sent_local = True
            except discord.HTTPException:
                pass

        if central_channel is not None:
            central_embed = embed.copy()
            central_embed.title = f"ONYX Central Report • #{central_number:05d}"
            try:
                await central_channel.send(
                    embed=central_embed,
                    allowed_mentions=discord.AllowedMentions.none()
                )
                sent_central = True
            except discord.HTTPException:
                pass

        if sent_local or sent_central:
            destinations = []
            if sent_central:
                destinations.append("ONYX staff")
            if sent_local:
                destinations.append("this server's staff")
            await ctx.send(
                f"Your report was submitted successfully to {' and '.join(destinations)}. "
                f"Central reference: **#{central_number:05d}**." if sent_central
                else "Your report was submitted successfully.",
                delete_after=25
            )
        else:
            await ctx.send(
                "I couldn't deliver your report. Please contact a server administrator or the ONYX owner."
            )


async def setup(bot):
    await bot.add_cog(Reports(bot))
