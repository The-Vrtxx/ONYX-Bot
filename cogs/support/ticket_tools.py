import asyncio
import io
import discord
from discord.ext import commands


def is_ticket_staff(member):
    return member.guild_permissions.manage_channels or any(
        role.permissions.manage_channels for role in member.roles
    )


class TicketTools(commands.Cog):
    """Command-based tools for ONYX's existing button ticket system."""

    def __init__(self, bot):
        self.bot = bot
        self.locks = set()

    async def cog_load(self):
        # Keep the original onyx_tickets table and its existing records intact.
        if getattr(self.bot.db, "backend", "sqlite") == "postgres":
            await self.bot.db.execute(
                "ALTER TABLE onyx_tickets ADD COLUMN IF NOT EXISTS priority TEXT NOT NULL DEFAULT 'normal'"
            )
            await self.bot.db.execute(
                "ALTER TABLE onyx_tickets ADD COLUMN IF NOT EXISTS closed_by BIGINT"
            )
        else:
            rows = await self.bot.db.fetchall("PRAGMA table_info(onyx_tickets)")
            columns = {row["name"] for row in rows}
            if "priority" not in columns:
                await self.bot.db.execute(
                    "ALTER TABLE onyx_tickets ADD COLUMN priority TEXT NOT NULL DEFAULT 'normal'"
                )
            if "closed_by" not in columns:
                await self.bot.db.execute(
                    "ALTER TABLE onyx_tickets ADD COLUMN closed_by BIGINT"
                )

        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_ticket_settings (
                guild_id BIGINT PRIMARY KEY,
                category_id BIGINT
            )
        """)

    async def current_ticket(self, ctx, include_closed=False):
        if not isinstance(ctx.channel, discord.TextChannel):
            return None
        status_clause = "" if include_closed else " AND status='open'"
        return await self.bot.db.fetchone(
            "SELECT * FROM onyx_tickets WHERE guild_id=? AND channel_id=?" + status_clause,
            (ctx.guild.id, ctx.channel.id)
        )

    async def require_staff(self, ctx):
        if not is_ticket_staff(ctx.author):
            await ctx.send("You need a staff role with **Manage Channels** to use that ticket action.")
            return False
        return True

    async def transcript(self, channel):
        lines = []
        async for message in channel.history(limit=500, oldest_first=True):
            stamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
            body = message.content or "[No text content]"
            if message.attachments:
                body += " | Attachments: " + ", ".join(a.url for a in message.attachments)
            if message.embeds:
                body += f" | Embeds: {len(message.embeds)}"
            lines.append(f"[{stamp}] {message.author} ({message.author.id}): {body}")
        content = "\n".join(lines) or "No messages."
        return discord.File(
            io.BytesIO(content.encode("utf-8")),
            filename=f"ticket-{channel.id}-transcript.txt"
        )

    async def send_transcript(self, guild, channel, file, note):
        settings = await self.bot.db.fetchone(
            "SELECT log_channel_id FROM guild_settings WHERE guild_id=?",
            (guild.id,)
        )
        log_channel = (
            guild.get_channel(int(settings["log_channel_id"]))
            if settings and settings["log_channel_id"] else None
        )
        if not isinstance(log_channel, discord.TextChannel):
            return False
        try:
            await log_channel.send(note, file=file)
            return True
        except discord.HTTPException:
            return False

    async def close_ticket(self, ctx, row):
        channel = ctx.channel
        if not isinstance(channel, discord.TextChannel):
            return await ctx.send("This command must be used inside a ticket channel.")
        if ctx.author.id != int(row["opener_id"]) and not is_ticket_staff(ctx.author):
            return await ctx.send("Only the ticket opener or ticket staff can close this ticket.")

        await ctx.send("Creating the transcript and closing this ticket…")
        file = await self.transcript(channel)
        saved = await self.send_transcript(
            ctx.guild, channel, file,
            f"Transcript for **{channel.name}** • closed by {ctx.author.mention}"
        )
        await self.bot.db.execute(
            "UPDATE onyx_tickets SET status='closed', closed_at=CURRENT_TIMESTAMP, closed_by=? "
            "WHERE id=?",
            (ctx.author.id, row["id"])
        )
        await asyncio.sleep(3)
        try:
            await channel.delete(reason=f"Ticket closed by {ctx.author}")
        except discord.HTTPException:
            await ctx.send("The ticket was marked closed, but I couldn't delete the channel.")
            return
        if not saved:
            try:
                await ctx.author.send(
                    f"Ticket #{int(row['id']):04d} was closed, but ONYX couldn't deliver its transcript. "
                    "Check the server's configured log channel."
                )
            except discord.HTTPException:
                pass

    async def ticket_row_for_channel(self, ctx):
        row = await self.current_ticket(ctx)
        if not row:
            await ctx.send("This channel isn't an open ONYX ticket.")
        return row

    @commands.command(name="claim", help="Claim the ticket you're currently in.")
    async def claim(self, ctx):
        if not await self.require_staff(ctx):
            return
        row = await self.ticket_row_for_channel(ctx)
        if not row:
            return
        if row["claimed_by"]:
            if int(row["claimed_by"]) == ctx.author.id:
                return await ctx.send("You already have this ticket claimed.")
            return await ctx.send(f"This ticket is already claimed by <@{int(row['claimed_by'])}>.")
        await self.bot.db.execute(
            "UPDATE onyx_tickets SET claimed_by=? WHERE id=?",
            (ctx.author.id, row["id"])
        )
        await ctx.send(f"🎫 Ticket **#{int(row['id']):04d}** claimed by {ctx.author.mention}.")

    @commands.command(name="unclaim", help="Release your claim on the current ticket.")
    async def unclaim(self, ctx):
        if not await self.require_staff(ctx):
            return
        row = await self.ticket_row_for_channel(ctx)
        if not row:
            return
        if not row["claimed_by"]:
            return await ctx.send("This ticket isn't currently claimed.")
        if int(row["claimed_by"]) != ctx.author.id and not ctx.author.guild_permissions.administrator:
            return await ctx.send("Only the staff member who claimed this ticket or an administrator can unclaim it.")
        await self.bot.db.execute(
            "UPDATE onyx_tickets SET claimed_by=NULL WHERE id=?",
            (row["id"],)
        )
        await ctx.send(f"Ticket **#{int(row['id']):04d}** is now unclaimed.")

    @commands.group(name="ticket", invoke_without_command=True,
                    help="Manage tickets: claim, unclaim, add, remove, rename, priority, close, reopen, transfer, info, list, category.")
    async def ticket(self, ctx):
        await ctx.send_help(ctx.command)

    @ticket.command(name="claim", help="Claim the current ticket.")
    async def ticket_claim(self, ctx):
        await ctx.invoke(self.claim)

    @ticket.command(name="unclaim", help="Unclaim the current ticket.")
    async def ticket_unclaim(self, ctx):
        await ctx.invoke(self.unclaim)

    @ticket.command(name="add", help="Give a member access to the current ticket.")
    async def ticket_add(self, ctx, member: discord.Member):
        if not await self.require_staff(ctx):
            return
        row = await self.ticket_row_for_channel(ctx)
        if not row:
            return
        try:
            await ctx.channel.set_permissions(
                member, view_channel=True, send_messages=True,
                read_message_history=True, attach_files=True,
                reason=f"Added to ticket by {ctx.author}"
            )
        except discord.HTTPException:
            return await ctx.send("I couldn't update that member's ticket access.")
        await ctx.send(f"Added {member.mention} to this ticket.")

    @ticket.command(name="remove", help="Remove a member's access to the current ticket.")
    async def ticket_remove(self, ctx, member: discord.Member):
        if not await self.require_staff(ctx):
            return
        row = await self.ticket_row_for_channel(ctx)
        if not row:
            return
        if member.id == int(row["opener_id"]):
            return await ctx.send("You can't remove the ticket opener.")
        try:
            await ctx.channel.set_permissions(
                member, overwrite=None, reason=f"Removed from ticket by {ctx.author}"
            )
        except discord.HTTPException:
            return await ctx.send("I couldn't remove that member's ticket access.")
        await ctx.send(f"Removed {member.mention} from this ticket.")

    @ticket.command(name="rename", help="Rename the current ticket channel.")
    async def ticket_rename(self, ctx, *, name: str):
        if not await self.require_staff(ctx):
            return
        row = await self.ticket_row_for_channel(ctx)
        if not row:
            return
        name = name.lower().replace(" ", "-")
        safe = "".join(ch for ch in name if ch.isalnum() or ch in "-_")[:90].strip("-_")
        if not safe:
            return await ctx.send("Use a name containing letters or numbers.")
        try:
            await ctx.channel.edit(name=safe, reason=f"Ticket renamed by {ctx.author}")
        except discord.HTTPException:
            return await ctx.send("I couldn't rename this ticket.")
        await ctx.send(f"Ticket renamed to **{safe}**.")

    @ticket.command(name="priority", help="Set ticket priority: low, normal, high, urgent.")
    async def ticket_priority(self, ctx, priority: str):
        if not await self.require_staff(ctx):
            return
        row = await self.ticket_row_for_channel(ctx)
        if not row:
            return
        priority = priority.lower()
        if priority not in {"low", "normal", "high", "urgent"}:
            return await ctx.send("Choose: `low`, `normal`, `high`, or `urgent`.")
        await self.bot.db.execute(
            "UPDATE onyx_tickets SET priority=? WHERE id=?",
            (priority, row["id"])
        )
        await ctx.send(f"Ticket **#{int(row['id']):04d}** priority set to **{priority.upper()}**.")

    @ticket.command(name="transfer", help="Transfer the current ticket to another staff member.")
    async def ticket_transfer(self, ctx, member: discord.Member):
        if not await self.require_staff(ctx):
            return
        row = await self.ticket_row_for_channel(ctx)
        if not row:
            return
        if not is_ticket_staff(member):
            return await ctx.send("That member doesn't have Manage Channels through a role or permission.")
        await self.bot.db.execute(
            "UPDATE onyx_tickets SET claimed_by=? WHERE id=?",
            (member.id, row["id"])
        )
        await ctx.send(f"Ticket **#{int(row['id']):04d}** transferred to {member.mention}.")

    @ticket.command(name="info", help="Show information about the current ticket.")
    async def ticket_info(self, ctx):
        row = await self.current_ticket(ctx, include_closed=True)
        if not row:
            return await ctx.send("This channel isn't registered as an ONYX ticket.")
        claimed = f"<@{int(row['claimed_by'])}>" if row["claimed_by"] else "Unclaimed"
        embed = discord.Embed(
            title=f"Ticket #{int(row['id']):04d}",
            color=discord.Color.dark_teal()
        )
        embed.add_field(name="Opener", value=f"<@{int(row['opener_id'])}>")
        embed.add_field(name="Status", value=str(row["status"]).title())
        embed.add_field(name="Claimed by", value=claimed)
        embed.add_field(name="Priority", value=str(row["priority"]).upper())
        embed.add_field(name="Created", value=str(row["created_at"])[:100], inline=False)
        if row["closed_at"]:
            embed.add_field(name="Closed", value=str(row["closed_at"])[:100], inline=False)
        await ctx.send(embed=embed)

    @ticket.command(name="list", help="List open tickets in this server.")
    async def ticket_list(self, ctx):
        if not await self.require_staff(ctx):
            return
        rows = await self.bot.db.fetchall(
            "SELECT id,channel_id,opener_id,claimed_by,priority FROM onyx_tickets "
            "WHERE guild_id=? AND status='open' ORDER BY id DESC LIMIT 20",
            (ctx.guild.id,)
        )
        if not rows:
            return await ctx.send("There are no open tickets.")
        lines = []
        for row in rows:
            channel = ctx.guild.get_channel(int(row["channel_id"]))
            channel_text = channel.mention if channel else f"`deleted channel {row['channel_id']}`"
            claimed = f"<@{int(row['claimed_by'])}>" if row["claimed_by"] else "Unclaimed"
            lines.append(
                f"**#{int(row['id']):04d}** {channel_text} • <@{int(row['opener_id'])}> "
                f"• {str(row['priority']).upper()} • {claimed}"
            )
        await ctx.send(embed=discord.Embed(
            title="Open tickets",
            description="\n".join(lines),
            color=discord.Color.dark_teal()
        ))

    @ticket.command(name="close", help="Close the current ticket and save a transcript.")
    async def ticket_close(self, ctx):
        row = await self.ticket_row_for_channel(ctx)
        if row:
            await self.close_ticket(ctx, row)

    @ticket.command(name="category", help="Set the category used for newly opened tickets.")
    @commands.has_guild_permissions(manage_guild=True)
    async def ticket_category(self, ctx, category: discord.CategoryChannel = None):
        if category is None:
            await self.bot.db.execute(
                "INSERT INTO onyx_ticket_settings (guild_id,category_id) VALUES (?,NULL) "
                "ON CONFLICT(guild_id) DO UPDATE SET category_id=NULL",
                (ctx.guild.id,)
            )
            return await ctx.send("New tickets will be created outside a category.")
        await self.bot.db.execute(
            "INSERT INTO onyx_ticket_settings (guild_id,category_id) VALUES (?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET category_id=excluded.category_id",
            (ctx.guild.id, category.id)
        )
        await ctx.send(f"New tickets will be created under {category.mention}.")

    @ticket.command(name="reopen", help="Reopen a closed ticket by its ticket number.")
    async def ticket_reopen(self, ctx, ticket_number: int):
        if not await self.require_staff(ctx):
            return
        row = await self.bot.db.fetchone(
            "SELECT * FROM onyx_tickets WHERE guild_id=? AND id=? AND status='closed'",
            (ctx.guild.id, ticket_number)
        )
        if not row:
            return await ctx.send("I couldn't find that closed ticket number.")
        opener = ctx.guild.get_member(int(row["opener_id"]))
        if opener is None:
            return await ctx.send("The original ticket opener is no longer in this server.")
        existing = await self.bot.db.fetchone(
            "SELECT channel_id FROM onyx_tickets WHERE guild_id=? AND opener_id=? AND status='open'",
            (ctx.guild.id, opener.id)
        )
        if existing and ctx.guild.get_channel(int(existing["channel_id"])):
            return await ctx.send(f"That member already has an open ticket: <#{int(existing['channel_id'])}>.")
        settings = await self.bot.db.fetchone(
            "SELECT category_id FROM onyx_ticket_settings WHERE guild_id=?",
            (ctx.guild.id,)
        )
        category = ctx.guild.get_channel(int(settings["category_id"])) if settings and settings["category_id"] else None
        overwrites = {
            ctx.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            opener: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, attach_files=True
            ),
        }
        for role in ctx.guild.roles:
            if role != ctx.guild.default_role and role.permissions.manage_channels:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True, attach_files=True
                )
        if ctx.guild.me:
            overwrites[ctx.guild.me] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True,
                read_message_history=True, attach_files=True
            )
        try:
            channel = await ctx.guild.create_text_channel(
                name=f"ticket-{ticket_number:04d}",
                category=category if isinstance(category, discord.CategoryChannel) else None,
                overwrites=overwrites,
                topic=f"Reopened ONYX ticket #{ticket_number:04d} for user {opener.id}",
                reason=f"Ticket reopened by {ctx.author}"
            )
        except discord.HTTPException:
            return await ctx.send("I couldn't recreate the ticket channel. Check ONYX's channel permissions.")
        await self.bot.db.execute(
            "UPDATE onyx_tickets SET channel_id=?,status='open',closed_at=NULL,closed_by=NULL,claimed_by=NULL "
            "WHERE id=?",
            (channel.id, ticket_number)
        )
        await channel.send(
            f"{opener.mention}, this ticket has been reopened by staff. Continue the conversation here.",
            allowed_mentions=discord.AllowedMentions(users=True)
        )
        await ctx.send(f"Reopened ticket **#{ticket_number:04d}**: {channel.mention}")

    @commands.Cog.listener()
    async def on_message(self, message):
        # No message processing here; this listener is intentionally absent of side effects.
        return


async def setup(bot):
    await bot.add_cog(TicketTools(bot))
