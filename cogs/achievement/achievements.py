import discord
from discord.ext import commands
from cogs.achievements.definitions import ACHIEVEMENTS,CATEGORIES
from cogs.achievements.engine import ensure_tables,get_unlocks,get_titles,get_equipped_title

class CategoryView(discord.ui.View):
    def __init__(self,cog,viewer_id,target_id):
        super().__init__(timeout=120); self.cog=cog; self.viewer_id=viewer_id; self.target_id=target_id
        sel=discord.ui.Select(placeholder="Choose achievement category",options=[discord.SelectOption(label="All",value="all")]+[discord.SelectOption(label=v[0],value=k) for k,v in CATEGORIES.items()])
        sel.callback=self.choose; self.add_item(sel)
    async def choose(self,interaction):
        if interaction.user.id!=self.viewer_id: return await interaction.response.send_message("This menu belongs to another member.",ephemeral=True)
        await interaction.response.edit_message(embed=await self.cog.make_embed(self.target_id,self.selected if hasattr(self,"selected") else "all",interaction.data["values"][0]),view=self)

class Achievements(commands.Cog):
    def __init__(self,bot): self.bot=bot
    async def cog_load(self): await ensure_tables(self.bot.db)
    async def make_embed(self,uid,category="all",selected=None):
        category=selected or category
        rows=await get_unlocks(self.bot.db,uid); unlocked={r["achievement_id"] for r in rows}
        items=ACHIEVEMENTS.items() if category=="all" else CATEGORIES.get(category,("",{}))[1].items()
        lines=[f"{d['icon']} **{d['name']}** — {d['tier']}" if aid in unlocked else f"🔒 **{d['name']}** — {d['tier']}" for aid,d in items]
        e=discord.Embed(title="🏆 ONYX Achievement Collection",description=f"**{len(unlocked)}/50** regular achievements unlocked",color=discord.Color.from_rgb(44,38,67))
        e.add_field(name="Achievements",value="\n".join(lines)[:1024] or "None",inline=False)
        titles=await get_titles(self.bot.db,uid); equipped=await get_equipped_title(self.bot.db,uid)
        e.add_field(name="Titles",value=f"Equipped: **{equipped or 'None'}**\nUnlocked: {', '.join(titles) or 'None'}",inline=False)
        e.set_footer(text="Secret achievements are discovered separately with ,secrets.")
        return e
    @commands.command(name="achievements",help="View your ONYX achievement collection.")
    async def achievements(self,ctx,member:discord.Member=None):
        member=member or ctx.author
        await ctx.send(embed=await self.make_embed(member.id),view=CategoryView(self,ctx.author.id,member.id))
    @commands.command(name="achievementleaderboard",aliases=["achievementlb"],help="View the ONYX achievement leaderboard.")
    async def leaderboard(self,ctx):
        rows=await self.bot.db.fetchall("SELECT user_id,COUNT(*) AS total FROM onyx_achievement_unlocks GROUP BY user_id ORDER BY total DESC LIMIT 10")
        await ctx.send("🏆 **ONYX Achievement Leaderboard**\n"+("\n".join(f"`{i}.` <@{r['user_id']}> — **{r['total']}**" for i,r in enumerate(rows,1)) or "No unlocks yet."))
    @commands.command(name="equiptitle",help="Equip an achievement title you have earned.")
    async def equiptitle(self,ctx,*,title:str):
        titles=await get_titles(self.bot.db,ctx.author.id); match=next((t for t in titles if t.casefold()==title.casefold()),None)
        if not match: return await ctx.send("You haven't unlocked that title.")
        await self.bot.db.execute("INSERT INTO onyx_achievement_equipped(user_id,title) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET title=excluded.title",(ctx.author.id,match))
        await ctx.send(f"✨ Equipped **{match}**.")
    @commands.command(name="unequiptitle",help="Remove your equipped achievement title.")
    async def unequiptitle(self,ctx):
        await self.bot.db.execute("DELETE FROM onyx_achievement_equipped WHERE user_id=?",(ctx.author.id,))
        await ctx.send("Title unequipped.")
    @commands.Cog.listener()
    async def on_command_completion(self,ctx):
        if ctx.author.bot: return
        try:
            from cogs.achievements.engine import record_command
            from cogs.achievements.secrets import secret_event
            await record_command(self.bot,ctx)
            await secret_event(self.bot,ctx.author,"command",ctx.guild,ctx.command.qualified_name.split()[-1].casefold())
        except Exception: pass
    @commands.Cog.listener()
    async def on_message(self,message):
        if message.author.bot or not message.guild: return
        try:
            from cogs.achievements.engine import record_message
            from cogs.achievements.secrets import secret_event
            await record_message(self.bot,message)
            await secret_event(self.bot,message.author,"message",message.guild)
        except Exception: pass

async def setup(bot):
    await bot.add_cog(Achievements(bot))
