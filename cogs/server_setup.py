import discord
from discord.ext import commands

class ServerSetup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(name="setup", invoke_without_command=True, help="Show the ONYX setup checklist for this server.")
    @commands.check(lambda ctx: ctx.guild is not None and (ctx.guild.owner_id == ctx.author.id or ctx.author.guild_permissions.manage_guild))
    async def setup(self, ctx: commands.Context):
        if ctx.guild is None:
            return await ctx.send("Use this command inside a server.")
        g = ctx.guild
        row = await self.bot.db.fetchone("SELECT log_channel_id,welcome_channel_id,xp_enabled,automod_enabled FROM guild_settings WHERE guild_id=?", (g.id,))
        log_channel = getattr(g.get_channel(row["log_channel_id"]), "mention", "Not configured") if row and row["log_channel_id"] else "Not configured"
        welcome_channel = getattr(g.get_channel(row["welcome_channel_id"]), "mention", "Not configured") if row and row["welcome_channel_id"] else "Not configured"
        embed = discord.Embed(title=f"ONYX setup • {g.name}", description="Each Discord server has independent settings and records.", color=discord.Color.dark_grey())
        embed.add_field(name="Logging channel", value=log_channel, inline=True)
        embed.add_field(name="Welcome channel", value=welcome_channel, inline=True)
        embed.add_field(name="Leveling", value="Enabled" if not row or row["xp_enabled"] else "Disabled", inline=True)
        embed.add_field(name="Automod", value="Enabled" if row and row["automod_enabled"] else "Disabled", inline=True)
        embed.set_footer(text="Use the configuration commands to customize this server.")
        await ctx.send(embed=embed)

    @setup.command(name="jail", help="Create the private ONYX jail role, category, and channel.")
    @commands.has_guild_permissions(manage_guild=True)
    async def setup_jail(self, ctx):
        jail_cog = self.bot.get_cog("Jail")
        if not jail_cog:
            return await ctx.send("The jail module isn't loaded. Check the Render logs and make sure `cogs/jail.py` was uploaded.")
        await jail_cog.setup_jail(ctx)

    @commands.command(name="settings", help="View this server's ONYX configuration.")
    @commands.check(lambda ctx: ctx.guild is not None and (ctx.guild.owner_id == ctx.author.id or ctx.author.guild_permissions.manage_guild))
    async def settings(self, ctx: commands.Context):
        if ctx.guild is None:
            return await ctx.send("Use this command inside a server.")
        row = await self.bot.db.fetchone("SELECT * FROM guild_settings WHERE guild_id=?", (ctx.guild.id,))
        if not row:
            return await ctx.send("No settings saved yet. ONYX will use its defaults.")
        embed = discord.Embed(title=f"ONYX settings • {ctx.guild.name}", color=discord.Color.dark_grey())
        for key in ("automod_enabled", "block_invites", "block_links", "spam_limit", "spam_window", "xp_enabled"):
            embed.add_field(name=key.replace("_", " ").title(), value=str(row[key]), inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="serverdata", help="Explain what ONYX stores for this server.")
    @commands.check(lambda ctx: ctx.guild is not None and (ctx.guild.owner_id == ctx.author.id or ctx.author.guild_permissions.manage_guild))
    async def serverdata(self, ctx: commands.Context):
        if ctx.guild is None:
            return await ctx.send("Use this command inside a server.")
        gid = ctx.guild.id
        counts = {}
        for table in ("mod_cases", "warnings", "levels", "custom_commands", "embed_templates"):
            row = await self.bot.db.fetchone(f"SELECT COUNT(*) AS n FROM {table} WHERE guild_id=?", (gid,))
            counts[table] = row["n"]
        embed = discord.Embed(title=f"ONYX data • {ctx.guild.name}", description="Counts are limited to this server's records.", color=discord.Color.dark_grey())
        for table, count in counts.items():
            embed.add_field(name=table.replace("_", " ").title(), value=str(count), inline=True)
        embed.set_footer(text="For deletion or privacy requests, contact the bot operator.")
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(ServerSetup(bot))
