import discord
from discord.ext import commands

class ModerationPlus(commands.Cog):
    """Additional moderation tools that complement the existing moderation cog."""
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="modnote", help="Save a private staff note about a member.")
    @commands.has_permissions(moderate_members=True)
    async def modnote(self, ctx, member: discord.Member, *, note: str):
        if len(note) > 1500:
            return await ctx.send("Keep the note under 1,500 characters.")
        await self.bot.db.execute(
            "INSERT INTO onyx_mod_notes (guild_id,user_id,moderator_id,note) VALUES (?,?,?,?)",
            (ctx.guild.id, member.id, ctx.author.id, note))
        await ctx.send(f"Staff note saved for **{member}**. It is only viewable with the staff note command.")

    @commands.command(name="modnotes", help="View saved staff notes for a member.")
    @commands.has_permissions(moderate_members=True)
    async def modnotes(self, ctx, member: discord.Member):
        rows = await self.bot.db.fetchall(
            "SELECT moderator_id,note,created_at FROM onyx_mod_notes "
            "WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 10",
            (ctx.guild.id, member.id))
        if not rows:
            return await ctx.send("No staff notes are saved for that member.")
        embed = discord.Embed(title=f"Staff notes • {member}", color=discord.Color.dark_grey())
        for row in rows:
            stamp = str(row["created_at"])
            embed.add_field(name=f"By {row['moderator_id']} • {stamp[:32]}",
                            value=str(row["note"])[:1024], inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="nick", help="Set a member's server nickname.")
    @commands.has_permissions(manage_nicknames=True)
    async def nick(self, ctx, member: discord.Member, *, nickname: str = None):
        if member == ctx.guild.owner or member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            return await ctx.send("Discord role hierarchy prevents you from changing that member's nickname.")
        if nickname is not None and len(nickname) > 32:
            return await ctx.send("Nicknames must be 32 characters or fewer.")
        try:
            await member.edit(nick=nickname, reason=f"Nickname changed by {ctx.author}")
        except discord.Forbidden:
            return await ctx.send("I don't have permission to change that nickname.")
        await ctx.send(f"Updated nickname for **{member}**.")

    @commands.command(name="role_add", help="Give a member a role.")
    @commands.has_permissions(manage_roles=True)
    async def role_add(self, ctx, member: discord.Member, *, role: discord.Role):
        if role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            return await ctx.send("You cannot manage a role at or above your highest role.")
        if role >= ctx.guild.me.top_role:
            return await ctx.send("Move ONYX's role above that role first.")
        await member.add_roles(role, reason=f"Role added by {ctx.author}")
        await ctx.send(f"Added {role.mention} to {member.mention}.")

    @commands.command(name="role_remove", help="Remove a role from a member.")
    @commands.has_permissions(manage_roles=True)
    async def role_remove(self, ctx, member: discord.Member, *, role: discord.Role):
        if role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            return await ctx.send("You cannot manage a role at or above your highest role.")
        if role >= ctx.guild.me.top_role:
            return await ctx.send("Move ONYX's role above that role first.")
        await member.remove_roles(role, reason=f"Role removed by {ctx.author}")
        await ctx.send(f"Removed {role.mention} from {member.mention}.")

async def setup(bot):
    await bot.add_cog(ModerationPlus(bot))
