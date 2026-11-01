from datetime import timedelta
import discord
from discord import app_commands
from discord.ext import commands

class Moderation(commands.Cog):
    def __init__(self, bot): self.bot = bot

    async def create_case(self, guild, member, moderator, action, reason):
        cursor = await self.bot.db.execute(
            "INSERT INTO mod_cases (guild_id,user_id,moderator_id,action,reason) VALUES (?,?,?,?,?)",
            (guild.id, member.id, moderator.id, action, reason))
        return cursor.lastrowid

    async def log_action(self, guild, title, description):
        row = await self.bot.db.fetchone("SELECT log_channel_id FROM guild_settings WHERE guild_id=?", (guild.id,))
        if row and row["log_channel_id"]:
            channel = guild.get_channel(row["log_channel_id"])
            if channel:
                try:
                    await channel.send(embed=discord.Embed(title=title, description=description, color=discord.Color.orange()))
                except discord.HTTPException:
                    pass

    @app_commands.command(name="ban", description="Ban a member from this server.")
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        if member.id == interaction.user.id or member.top_role >= interaction.user.top_role:
            return await interaction.response.send_message("You can't ban yourself or someone with an equal/higher role.", ephemeral=True)
        await member.ban(reason=f"{interaction.user}: {reason}")
        await interaction.response.send_message(f"🔨 Banned **{member}**. Reason: {reason}")
        await self.log_action(interaction.guild, "Member banned", f"{member.mention} — {reason} (by {interaction.user.mention})")

    @app_commands.command(name="kick", description="Kick a member from this server.")
    @app_commands.checks.has_permissions(kick_members=True)
    @app_commands.checks.bot_has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        if member.id == interaction.user.id or member.top_role >= interaction.user.top_role:
            return await interaction.response.send_message("You can't kick yourself or someone with an equal/higher role.", ephemeral=True)
        await member.kick(reason=f"{interaction.user}: {reason}")
        await interaction.response.send_message(f"👢 Kicked **{member}**. Reason: {reason}")
        await self.log_action(interaction.guild, "Member kicked", f"{member} — {reason} (by {interaction.user.mention})")

    @app_commands.command(name="timeout", description="Timeout a member for a number of minutes.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    async def timeout(self, interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 40320], reason: str = "No reason provided"):
        if member.id == interaction.user.id or member.top_role >= interaction.user.top_role:
            return await interaction.response.send_message("You can't timeout yourself or someone with an equal/higher role.", ephemeral=True)
        until = discord.utils.utcnow() + timedelta(minutes=minutes)
        await member.timeout(until, reason=f"{interaction.user}: {reason}")
        await interaction.response.send_message(f"⏳ Timed out **{member}** for {minutes} minutes. Reason: {reason}")
        await self.log_action(interaction.guild, "Member timed out", f"{member.mention} for {minutes} minutes — {reason}")

    @app_commands.command(name="untimeout", description="Remove a member's timeout.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    async def untimeout(self, interaction: discord.Interaction, member: discord.Member):
        await member.timeout(None, reason=f"Timeout removed by {interaction.user}")
        await interaction.response.send_message(f"Timeout removed for {member.mention}.")

    @app_commands.command(name="warn", description="Give a member a recorded warning.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        if member.id == interaction.user.id:
            return await interaction.response.send_message("You can't warn yourself.", ephemeral=True)
        await self.bot.db.execute(
            "INSERT INTO warnings (guild_id,user_id,moderator_id,reason) VALUES (?,?,?,?)",
            (interaction.guild.id, member.id, interaction.user.id, reason))
        case_id = await self.create_case(interaction.guild, member, interaction.user, "warn", reason)
        await interaction.response.send_message(f"⚠️ Warned {member.mention}. Case `#{case_id}`. Reason: {reason}")
        policy = await self.bot.db.fetchone("SELECT threshold,action FROM warn_settings WHERE guild_id=?", (interaction.guild.id,))
        count_row = await self.bot.db.fetchone("SELECT COUNT(*) AS n FROM warnings WHERE guild_id=? AND user_id=?", (interaction.guild.id, member.id))
        if policy and count_row and count_row["n"] == policy["threshold"]:
            action = policy["action"]
            try:
                if action == "timeout":
                    await member.timeout(timedelta(minutes=10), reason=f"Automatic escalation after {count_row['n']} warnings")
                elif action == "kick":
                    await member.kick(reason=f"Automatic escalation after {count_row['n']} warnings")
                elif action == "ban":
                    await member.ban(reason=f"Automatic escalation after {count_row['n']} warnings")
                await interaction.followup.send(f"Escalation applied: **{action}** after {count_row['n']} warnings.", ephemeral=True)
            except discord.HTTPException:
                await interaction.followup.send("Warning saved, but the configured escalation could not be applied. Check role hierarchy and permissions.", ephemeral=True)
        await self.log_action(interaction.guild, "Member warned", f"{member.mention} — {reason}")

    @app_commands.command(name="warnings", description="View a member's warning history.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        rows = await self.bot.db.fetchall(
            "SELECT id, moderator_id, reason, created_at FROM warnings WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 10",
            (interaction.guild.id, member.id))
        if not rows:
            return await interaction.response.send_message(f"{member} has no warnings.", ephemeral=True)
        embed = discord.Embed(title=f"Warnings for {member}", color=discord.Color.orange())
        for row in rows:
            embed.add_field(name=f"#{row['id']} • {row['created_at']}", value=f"{row['reason']}\nModerator: <@{row['moderator_id']}>", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="purge", description="Delete a number of recent messages.")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.checks.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def purge(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"Deleted {len(deleted)} messages.", ephemeral=True)


    @app_commands.command(name="modlogs", description="View a member's recent moderation cases.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def modlogs(self, interaction: discord.Interaction, member: discord.Member):
        rows = await self.bot.db.fetchall(
            "SELECT id,action,reason,moderator_id,created_at FROM mod_cases WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 10",
            (interaction.guild.id, member.id))
        if not rows:
            return await interaction.response.send_message("No moderation cases found.", ephemeral=True)
        embed = discord.Embed(title=f"Moderation history: {member}", color=discord.Color.orange())
        for row in rows:
            embed.add_field(name=f"Case #{row['id']} • {row['action']} • {row['created_at']}",
                            value=f"Reason: {row['reason']}\\nModerator: <@{row['moderator_id']}>", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="case", description="Look up a moderation case by ID.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def case(self, interaction: discord.Interaction, case_id: int):
        row = await self.bot.db.fetchone(
            "SELECT * FROM mod_cases WHERE guild_id=? AND id=?", (interaction.guild.id, case_id))
        if not row:
            return await interaction.response.send_message("Case not found.", ephemeral=True)
        embed = discord.Embed(title=f"Moderation case #{row['id']}", color=discord.Color.orange())
        embed.add_field(name="Action", value=row["action"])
        embed.add_field(name="Member", value=f"<@{row['user_id']}>")
        embed.add_field(name="Moderator", value=f"<@{row['moderator_id']}>")
        embed.add_field(name="Reason", value=row["reason"], inline=False)
        embed.add_field(name="Date", value=row["created_at"], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="warn_escalation", description="Configure automatic action after repeated warnings.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def warn_escalation(self, interaction: discord.Interaction,
                              threshold: app_commands.Range[int, 2, 20],
                              action: app_commands.Choice[str]):
        await self.bot.db.execute(
            "INSERT INTO warn_settings (guild_id,threshold,action) VALUES (?,?,?) ON CONFLICT(guild_id) DO UPDATE SET threshold=excluded.threshold,action=excluded.action",
            (interaction.guild.id, threshold, action.value))
        await interaction.response.send_message(
            f"After **{threshold}** warnings, the configured action will be **{action.value}**.", ephemeral=True)

    @warn_escalation.autocomplete("action")
    async def escalation_action_choices(self, interaction: discord.Interaction, current: str):
        return [app_commands.Choice(name=x, value=x) for x in ("timeout", "kick", "ban") if current.lower() in x]

    @app_commands.command(name="lock", description="Lock this text channel for @everyone.")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True)
    async def lock(self, interaction: discord.Interaction):
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite,
                                                  reason=f"Channel locked by {interaction.user}")
        await interaction.response.send_message(f"🔒 {interaction.channel.mention} is locked.")

    @app_commands.command(name="unlock", description="Unlock this text channel for @everyone.")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True)
    async def unlock(self, interaction: discord.Interaction):
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = None
        await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite,
                                                  reason=f"Channel unlocked by {interaction.user}")
        await interaction.response.send_message(f"🔓 {interaction.channel.mention} is unlocked.")

    @app_commands.command(name="slowmode", description="Set this channel's slowmode in seconds.")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True)
    async def slowmode(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]):
        await interaction.channel.edit(slowmode_delay=seconds, reason=f"Slowmode set by {interaction.user}")
        await interaction.response.send_message(f"Slowmode set to **{seconds} seconds**.")

async def setup(bot): await bot.add_cog(Moderation(bot))
