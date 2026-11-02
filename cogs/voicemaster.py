import discord
from discord.ext import commands

class VoiceMaster(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.triggers = {}
        self.owners = {}

    @commands.command(name="voicemaster_set", help="Set a join-to-create voice channel.")
    @commands.has_permissions(manage_guild=True)
    async def voicemaster_set(self, ctx, channel: discord.VoiceChannel):
        self.triggers[ctx.guild.id] = channel.id
        await ctx.send(f"{channel.mention} is now the join-to-create channel. Setting resets after restart.")

    @commands.command(name="voicemaster_name", help="Rename your temporary voice room.")
    async def voicemaster_name(self, ctx, *, name: str):
        channel = ctx.author.voice.channel if ctx.author.voice else None
        if not channel or self.owners.get(channel.id) != ctx.author.id:
            return await ctx.send("Join a temporary room you own first.")
        await channel.edit(name=name[:90])
        await ctx.send(f"Room renamed to **{name[:90]}**.")

    @commands.command(name="voicemaster_limit", help="Set your temporary room limit.")
    async def voicemaster_limit(self, ctx, limit: int):
        channel = ctx.author.voice.channel if ctx.author.voice else None
        if not channel or self.owners.get(channel.id) != ctx.author.id:
            return await ctx.send("Join a temporary room you own first.")
        if not 0 <= limit <= 99:
            return await ctx.send("Choose 0 (unlimited) through 99.")
        await channel.edit(user_limit=limit)
        await ctx.send(f"Room limit set to **{limit or 'unlimited'}**.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if after.channel and self.triggers.get(member.guild.id) == after.channel.id:
            overwrites = {
                member.guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=True),
                member: discord.PermissionOverwrite(view_channel=True, connect=True)
            }
            room = await member.guild.create_voice_channel(name=f"{member.display_name}'s room"[:90], category=after.channel.category, overwrites=overwrites)
            self.owners[room.id] = member.id
            await member.move_to(room)
        if before.channel and before.channel.id in self.owners and not before.channel.members:
            self.owners.pop(before.channel.id, None)
            try:
                await before.channel.delete(reason="Empty ONYX temporary room")
            except discord.NotFound:
                pass

async def setup(bot):
    await bot.add_cog(VoiceMaster(bot))
