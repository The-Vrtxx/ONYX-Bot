import discord
from discord.ext import commands


class PermissionRefresh(commands.Cog):
    """Refresh ONYX mute and jail role overwrites after channels are added."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(
        name="updatepermissions",
        help="Reapply ONYX mute and jail permissions to all server channels."
    )
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.bot_has_guild_permissions(manage_roles=True, manage_channels=True)
    async def update_permissions(self, ctx):
        guild = ctx.guild
        mute_result = "Not configured"
        jail_result = "Not configured"
        failures = []

        # Refresh all three mute-role overwrites using the existing setup logic.
        mute_cog = self.bot.get_cog("MuteSetup")
        if mute_cog is not None:
            mute_config = await mute_cog.get_config(guild.id)
            if mute_config:
                try:
                    roles, _ = await mute_cog.ensure_roles(guild)
                    count, failed = await mute_cog.apply_channel_permissions(guild, roles)
                    mute_result = f"{count} channels updated"
                    failures.extend(f"Mute — #{name}" for name in failed)
                except (discord.Forbidden, discord.HTTPException):
                    mute_result = "Update failed — check Manage Roles/Channels"
            else:
                mute_result = "Not configured — run ,setupmute first"
        else:
            mute_result = "Mute system cog unavailable"

        # Reapply the Jailed role's hidden-channel overwrite everywhere except
        # the configured jail category and the dedicated jail channel.
        jail_cog = self.bot.get_cog("Jail")
        if jail_cog is not None:
            jail_config = await jail_cog.settings(guild.id)
            if jail_config:
                jail_role = guild.get_role(int(jail_config["role_id"]))
                jail_category_id = int(jail_config["category_id"])
                jail_channel_id = int(jail_config["channel_id"])

                if jail_role is None:
                    jail_result = "Configured Jailed role is missing — rerun ,setup jail"
                else:
                    changed = 0
                    for channel in guild.channels:
                        if channel.id in (jail_category_id, jail_channel_id):
                            continue
                        try:
                            await channel.set_permissions(
                                jail_role,
                                view_channel=False,
                                reason="ONYX permission refresh: keep jailed members out of this channel"
                            )
                            changed += 1
                        except (discord.Forbidden, discord.HTTPException):
                            failures.append(f"Jail — #{channel.name}")

                    jail_result = f"{changed} channels/categories updated"
            else:
                jail_result = "Not configured — run ,setup jail first"
        else:
            jail_result = "Jail system cog unavailable"

        embed = discord.Embed(
            title="ONYX Channel Permissions Refreshed",
            description=(
                f"**Mute roles:** {mute_result}\n"
                f"**Jailed role:** {jail_result}"
            ),
            color=discord.Color.dark_teal()
        )
        if failures:
            embed.add_field(
                name=f"Channels that could not be updated ({len(failures)})",
                value="\n".join(failures[:20])[:1024],
                inline=False
            )
            embed.set_footer(text="Check ONYX's Manage Channels permission and role hierarchy.")
        else:
            embed.set_footer(text="No channel permission errors were reported.")
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(PermissionRefresh(bot))
