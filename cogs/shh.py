import discord
from discord import app_commands
from discord.ext import commands


async def is_bot_owner(interaction: discord.Interaction) -> bool:
    """Restrict configuration commands to the bot owner in BOT_OWNER_ID."""
    return await interaction.client.is_owner(interaction.user)


class Shh(commands.Cog):
    """Private, per-server role grant command with bot-owner configuration."""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="shh",
        description="Quietly give a member the server's configured special role."
    )
    @app_commands.guild_only()
    async def shh(self, interaction: discord.Interaction, member: discord.Member):
        allowed = await self.bot.db.fetchone(
            "SELECT 1 FROM shh_whitelist WHERE guild_id=? AND user_id=?",
            (interaction.guild.id, interaction.user.id)
        )
        if not allowed:
            return await interaction.response.send_message(
                "You aren't authorized to use this command.", ephemeral=True
            )

        setting = await self.bot.db.fetchone(
            "SELECT role_id FROM shh_settings WHERE guild_id=?",
            (interaction.guild.id,)
        )
        if not setting:
            return await interaction.response.send_message(
                "The special role hasn't been configured for this server yet.",
                ephemeral=True
            )

        role = interaction.guild.get_role(setting["role_id"])
        if role is None:
            return await interaction.response.send_message(
                "The configured role no longer exists. Ask the bot owner to set it again.",
                ephemeral=True
            )
        if role.is_default() or role.managed or role >= interaction.guild.me.top_role:
            return await interaction.response.send_message(
                "I can't manage the configured role. Ask an administrator to move my bot role above it.",
                ephemeral=True
            )
        if member.id == self.bot.user.id:
            return await interaction.response.send_message(
                "I can't assign the role to myself.", ephemeral=True
            )
        if role in member.roles:
            return await interaction.response.send_message(
                f"{member.mention} already has **{role.name}**.", ephemeral=True
            )

        try:
            await member.add_roles(role, reason=f"Special /shh role grant by {interaction.user} ({interaction.user.id})")
        except discord.Forbidden:
            return await interaction.response.send_message(
                "Discord denied the role change. Check my Manage Roles permission and role hierarchy.",
                ephemeral=True
            )
        except discord.HTTPException:
            return await interaction.response.send_message(
                "Discord couldn't apply the role. Please try again.", ephemeral=True
            )

        # Private acknowledgement; the role grant itself is recorded in the audit log.
        await interaction.response.send_message(
            f"Done. **{role.name}** was assigned to {member.mention}.",
            ephemeral=True
        )

    @app_commands.command(
        name="shh_whitelist_add",
        description="(Bot owner) Allow a user to use /shh in this server."
    )
    @app_commands.guild_only()
    @app_commands.check(is_bot_owner)
    async def whitelist_add(self, interaction: discord.Interaction, user: discord.Member):
        await self.bot.db.execute(
            "INSERT INTO shh_whitelist (guild_id,user_id) VALUES (?,?) ON CONFLICT DO NOTHING",
            (interaction.guild.id, user.id)
        )
        await interaction.response.send_message(
            f"{user.mention} is now whitelisted for `/shh` in this server.",
            ephemeral=True
        )

    @app_commands.command(
        name="shh_whitelist_remove",
        description="(Bot owner) Remove a user's /shh access in this server."
    )
    @app_commands.guild_only()
    @app_commands.check(is_bot_owner)
    async def whitelist_remove(self, interaction: discord.Interaction, user: discord.Member):
        await self.bot.db.execute(
            "DELETE FROM shh_whitelist WHERE guild_id=? AND user_id=?",
            (interaction.guild.id, user.id)
        )
        await interaction.response.send_message(
            f"{user.mention} is no longer whitelisted for `/shh` in this server.",
            ephemeral=True
        )

    @app_commands.command(
        name="shh_set_role",
        description="(Bot owner) Choose the role that /shh grants in this server."
    )
    @app_commands.guild_only()
    @app_commands.check(is_bot_owner)
    async def set_role(self, interaction: discord.Interaction, role: discord.Role):
        if role.is_default() or role.managed:
            return await interaction.response.send_message(
                "Choose a normal, non-managed role (not @everyone).", ephemeral=True
            )
        if interaction.guild.me is None or role >= interaction.guild.me.top_role:
            return await interaction.response.send_message(
                "Move the bot's highest role above the role you want `/shh` to grant, then try again.",
                ephemeral=True
            )
        await self.bot.db.execute(
            """INSERT INTO shh_settings (guild_id,role_id) VALUES (?,?)
            ON CONFLICT(guild_id) DO UPDATE SET role_id=excluded.role_id""",
            (interaction.guild.id, role.id)
        )
        await interaction.response.send_message(
            f"`/shh` will now grant **{role.name}** in this server.",
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Shh(bot))
