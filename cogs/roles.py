import discord
from discord.ext import commands


class RoleToggleButton(discord.ui.View):
    def __init__(self, bot, role_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.role_id = role_id
        button = discord.ui.Button(label="Get role", style=discord.ButtonStyle.primary,
                                   custom_id=f"selfrole-panel:{role_id}")
        button.callback = self.toggle
        self.add_item(button)

    async def toggle(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if not role or role >= interaction.guild.me.top_role or role.managed:
            return await interaction.response.send_message("That role is no longer available.", ephemeral=True)
        allowed = await self.bot.db.fetchone(
            "SELECT 1 FROM self_roles WHERE guild_id=? AND role_id=?",
            (interaction.guild.id, role.id))
        if not allowed:
            return await interaction.response.send_message("That role is no longer self-assignable.", ephemeral=True)
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role, reason="Self-role panel")
            text = f"Removed {role.mention}."
        else:
            await interaction.user.add_roles(role, reason="Self-role panel")
            text = f"Added {role.mention}."
        await interaction.response.send_message(text, ephemeral=True)

class Roles(commands.Cog):
    def __init__(self, bot): self.bot = bot

    async def cog_load(self):
        rows = await self.bot.db.fetchall("SELECT DISTINCT role_id FROM role_panels")
        for row in rows:
            self.bot.add_view(RoleToggleButton(self.bot, row["role_id"]))

    @commands.command(name="selfrole_add", help="Allow members to self-assign a role.")
    @commands.has_permissions(manage_roles=True)
    async def add_selfrole(self, ctx: commands.Context, role: discord.Role):
        if role.is_default() or role.managed or role >= ctx.guild.me.top_role:
            return await ctx.send("I can't offer that role. Check its position and type.",)
        await self.bot.db.execute("INSERT INTO self_roles VALUES (?,?) ON CONFLICT DO NOTHING", (ctx.guild.id, role.id))
        await ctx.send(f"{role.mention} is now self-assignable.",)

    @commands.command(name="selfrole_remove", help="Remove a role from the self-assignable list.")
    @commands.has_permissions(manage_roles=True)
    async def remove_selfrole(self, ctx: commands.Context, role: discord.Role):
        await self.bot.db.execute("DELETE FROM self_roles WHERE guild_id=? AND role_id=?", (ctx.guild.id, role.id))
        await ctx.send(f"Removed {role.mention} from self-assignable roles.",)

    @commands.command(name="selfrole_list", help="List self-assignable roles.")
    async def list_selfroles(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall("SELECT role_id FROM self_roles WHERE guild_id=?", (ctx.guild.id,))
        roles = [ctx.guild.get_role(r["role_id"]) for r in rows]
        roles = [r.mention for r in roles if r]
        await ctx.send("**Self-assignable roles**\n" + ("\n".join(roles) if roles else "None configured."),)

    @commands.command(name="role", help="Give yourself or remove a self-assignable role.")
    async def selfrole(self, ctx: commands.Context, role: discord.Role):
        allowed = await self.bot.db.fetchone("SELECT 1 FROM self_roles WHERE guild_id=? AND role_id=?", (ctx.guild.id, role.id))
        if not allowed:
            return await ctx.send("That role isn't self-assignable.",)
        if role >= ctx.guild.me.top_role or role.managed:
            return await ctx.send("I can't manage that role. Ask an administrator to check my role position.",)
        member = ctx.author
        if role in member.roles:
            await member.remove_roles(role, reason="Self-role toggle")
            action = "Removed"
        else:
            await member.add_roles(role, reason="Self-role toggle")
            action = "Added"
        await ctx.send(f"{action} {role.mention}.",)


    @commands.command(name="rolepanel_create", help="Post a persistent self-role button panel.")
    @commands.has_permissions(manage_roles=True)
    async def rolepanel_create(self, ctx: commands.Context, role: discord.Role,
                               channel: discord.TextChannel, *, description: str = "Click below to toggle this role."):
        allowed = await self.bot.db.fetchone("SELECT 1 FROM self_roles WHERE guild_id=? AND role_id=?",
                                              (ctx.guild.id, role.id))
        if not allowed:
            return await ctx.send("Add this role with `,selfrole_add` first.",)
        view = RoleToggleButton(self.bot, role.id)
        embed = discord.Embed(title=f"Self role: {role.name}", help=description,
                              color=discord.Color.blurple())
        message = await channel.send(embed=embed, view=view)
        await self.bot.db.execute("INSERT INTO role_panels VALUES (?,?,?,?) ON CONFLICT DO NOTHING",
                                  (ctx.guild.id, channel.id, message.id, role.id))
        await ctx.send(f"Role panel posted in {channel.mention}.",)

async def setup(bot): await bot.add_cog(Roles(bot))
