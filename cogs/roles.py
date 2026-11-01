import discord
from discord import app_commands
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

    @app_commands.command(name="selfrole_add", description="Allow members to self-assign a role.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def add_selfrole(self, interaction: discord.Interaction, role: discord.Role):
        if role.is_default() or role.managed or role >= interaction.guild.me.top_role:
            return await interaction.response.send_message("I can't offer that role. Check its position and type.", ephemeral=True)
        await self.bot.db.execute("INSERT INTO self_roles VALUES (?,?) ON CONFLICT DO NOTHING", (interaction.guild.id, role.id))
        await interaction.response.send_message(f"{role.mention} is now self-assignable.", ephemeral=True)

    @app_commands.command(name="selfrole_remove", description="Remove a role from the self-assignable list.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def remove_selfrole(self, interaction: discord.Interaction, role: discord.Role):
        await self.bot.db.execute("DELETE FROM self_roles WHERE guild_id=? AND role_id=?", (interaction.guild.id, role.id))
        await interaction.response.send_message(f"Removed {role.mention} from self-assignable roles.", ephemeral=True)

    @app_commands.command(name="selfrole_list", description="List self-assignable roles.")
    async def list_selfroles(self, interaction: discord.Interaction):
        rows = await self.bot.db.fetchall("SELECT role_id FROM self_roles WHERE guild_id=?", (interaction.guild.id,))
        roles = [interaction.guild.get_role(r["role_id"]) for r in rows]
        roles = [r.mention for r in roles if r]
        await interaction.response.send_message("**Self-assignable roles**\n" + ("\n".join(roles) if roles else "None configured."), ephemeral=True)

    @app_commands.command(name="role", description="Give yourself or remove a self-assignable role.")
    async def selfrole(self, interaction: discord.Interaction, role: discord.Role):
        allowed = await self.bot.db.fetchone("SELECT 1 FROM self_roles WHERE guild_id=? AND role_id=?", (interaction.guild.id, role.id))
        if not allowed:
            return await interaction.response.send_message("That role isn't self-assignable.", ephemeral=True)
        if role >= interaction.guild.me.top_role or role.managed:
            return await interaction.response.send_message("I can't manage that role. Ask an administrator to check my role position.", ephemeral=True)
        member = interaction.user
        if role in member.roles:
            await member.remove_roles(role, reason="Self-role toggle")
            action = "Removed"
        else:
            await member.add_roles(role, reason="Self-role toggle")
            action = "Added"
        await interaction.response.send_message(f"{action} {role.mention}.", ephemeral=True)


    @app_commands.command(name="rolepanel_create", description="Post a persistent self-role button panel.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def rolepanel_create(self, interaction: discord.Interaction, role: discord.Role,
                               channel: discord.TextChannel, description: str = "Click below to toggle this role."):
        allowed = await self.bot.db.fetchone("SELECT 1 FROM self_roles WHERE guild_id=? AND role_id=?",
                                              (interaction.guild.id, role.id))
        if not allowed:
            return await interaction.response.send_message("Add this role with your prefix followed by `selfrole_add` first.", ephemeral=True)
        view = RoleToggleButton(self.bot, role.id)
        embed = discord.Embed(title=f"Self role: {role.name}", description=description,
                              color=discord.Color.blurple())
        await interaction.response.defer(ephemeral=True)
        message = await channel.send(embed=embed, view=view)
        await self.bot.db.execute("INSERT INTO role_panels VALUES (?,?,?,?) ON CONFLICT DO NOTHING",
                                  (interaction.guild.id, channel.id, message.id, role.id))
        await interaction.followup.send(f"Role panel posted in {channel.mention}.", ephemeral=True)

async def setup(bot): await bot.add_cog(Roles(bot))
