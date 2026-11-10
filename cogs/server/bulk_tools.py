import asyncio
import discord
from discord.ext import commands


class ConfirmBulkAction(discord.ui.View):
    def __init__(self, author_id: int, action):
        super().__init__(timeout=45)
        self.author_id = author_id
        self.action = action
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the moderator who started this action can confirm it.",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await self.action(interaction)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Action cancelled.", view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass


class BulkTools(commands.Cog):
    """Bulk message cleanup and human/bot role assignment."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="clearbots", aliases=["purgebots", "botclear", "bc"])
    @commands.guild_only()
    @commands.has_guild_permissions(manage_messages=True)
    @commands.bot_has_guild_permissions(manage_messages=True, read_message_history=True)
    async def clear_bots(self, ctx, scan_limit: int = 100):
        """Delete recent messages sent by bots only. Usage: ,clearbots [messages_to_scan]"""
        if scan_limit < 1 or scan_limit > 1000:
            return await ctx.send("Choose a scan amount between **1 and 1000**.")

        status = await ctx.send(
            f"🔎 Checking the latest **{scan_limit:,}** messages for bot-authored messages..."
        )
        deleted = []
        try:
            async for message in ctx.channel.history(limit=scan_limit):
                if message.author.bot:
                    deleted.append(message)
        except discord.Forbidden:
            return await status.edit(content="I can't read this channel's message history.")
        except discord.HTTPException:
            return await status.edit(content="Discord returned an error while checking message history.")

        if not deleted:
            return await status.edit(content="No bot messages were found in that scan.")

        # Purge handles Discord's 14-day bulk-delete limit and falls back to individual deletes.
        try:
            removed = await ctx.channel.purge(
                limit=scan_limit,
                check=lambda message: message.author.bot,
                bulk=True
            )
            await status.edit(
                content=f"🧹 Removed **{len(removed):,}** bot messages. "
                        f"Scanned the latest **{scan_limit:,}** messages."
            )
        except discord.Forbidden:
            await status.edit(content="I found bot messages, but I don't have permission to delete them.")
        except discord.HTTPException:
            await status.edit(content="Discord returned an error while deleting bot messages.")

    @commands.command(name="massrole", aliases=["bulkrole"])
    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    async def mass_role(self, ctx, group: str, role: discord.Role):
        """Add a role to humans or bots. Usage: ,massrole humans @Role | bots @Role"""
        group = group.casefold()
        if group not in ("human", "humans", "member", "members", "bot", "bots"):
            return await ctx.send(
                f"Use `{ctx.prefix}massrole humans @Role` or "
                f"`{ctx.prefix}massrole bots @Role`."
            )

        if role.is_default() or role.managed:
            return await ctx.send("I can't mass-assign the @everyone role or an integration-managed role.")
        if role >= ctx.guild.me.top_role:
            return await ctx.send("That role is at or above my highest role. Move ONYX's role above it.")
        if ctx.author != ctx.guild.owner and role >= ctx.author.top_role:
            return await ctx.send("You can only mass-assign roles below your highest role.")

        target_bots = group in ("bot", "bots")
        targets = [
            member for member in ctx.guild.members
            if member.bot == target_bots and role not in member.roles
        ]
        label = "bots" if target_bots else "human members"

        if not targets:
            return await ctx.send(f"All {label} already have {role.mention}, or no matching members were found.")

        async def perform(interaction):
            await interaction.followup.send(
                f"⏳ Assigning {role.mention} to **{len(targets):,}** {label}...",
                ephemeral=False
            )
            success = 0
            failed = 0
            for index, member in enumerate(targets, start=1):
                try:
                    await member.add_roles(role, reason=f"Bulk role assignment by {ctx.author} ({ctx.author.id})")
                    success += 1
                except (discord.Forbidden, discord.HTTPException):
                    failed += 1
                # Keep the request rate gentle on larger servers.
                if index % 5 == 0:
                    await asyncio.sleep(1)
            try:
                await interaction.followup.send(
                    f"✅ Finished assigning {role.mention} to {label}.\n"
                    f"**Added:** {success:,}  •  **Failed:** {failed:,}"
                )
            except discord.HTTPException:
                pass

        view = ConfirmBulkAction(ctx.author.id, perform)
        prompt = await ctx.send(
            f"**Confirm bulk role assignment**\n"
            f"Role: {role.mention}\n"
            f"Targets: **{len(targets):,} {label}**\n\n"
            "This will add the role only to matching members who don't already have it.",
            view=view
        )
        view.message = prompt

    @clear_bots.error
    async def clear_bots_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You need **Manage Messages** to use this command.")
        elif isinstance(error, commands.BotMissingPermissions):
            await ctx.send("I need **Manage Messages** and **Read Message History**.")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"Usage: `{ctx.prefix}clearbots [messages_to_scan]`")
        else:
            raise error

    @mass_role.error
    async def mass_role_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You need **Manage Roles** to use this command.")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"Usage: `{ctx.prefix}massrole humans @Role` or `{ctx.prefix}massrole bots @Role`")
        else:
            raise error


async def setup(bot):
    await bot.add_cog(BulkTools(bot))
