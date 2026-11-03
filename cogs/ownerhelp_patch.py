# ONYX Owner Command Directory
# Add this block to main.py immediately BEFORE: @bot.command(name="help")
# Then commit main.py and allow Render to redeploy.

@bot.command(
    name="ownerhelp",
    aliases=["ownercommands", "hiddencommands"],
    hidden=True
)
@commands.is_owner()
async def owner_help(ctx):
    """List every currently loaded hidden command. Bot owner only."""
    hidden_commands = sorted(
        (command for command in bot.walk_commands() if command.hidden),
        key=lambda command: command.qualified_name.casefold()
    )

    embed = discord.Embed(
        title="ONYX • Owner Command Directory",
        description=(
            "These commands are hidden from the public help menu. "
            "Some may have additional permission checks."
        ),
        color=discord.Color.from_rgb(44, 38, 67)
    )

    if not hidden_commands:
        embed.description = "No hidden commands are currently loaded."
    else:
        lines = []
        for command in hidden_commands:
            usage = _command_usage(ctx.prefix, command)
            description = command.help or command.brief or "No description available."
            lines.append(f"`{usage}`\n{description[:160]}")

        # Discord embed descriptions have a 4,096-character limit.
        pages = []
        current = ""
        for line in lines:
            addition = ("\n\n" if current else "") + line
            if len(current) + len(addition) > 3800:
                pages.append(current)
                current = line
            else:
                current += addition
        if current:
            pages.append(current)

        embed.description = pages[0]
        if len(pages) > 1:
            embed.set_footer(
                text=f"Showing page 1/{len(pages)}. "
                     f"{len(hidden_commands)} hidden commands total."
            )
        else:
            embed.set_footer(
                text=f"{len(hidden_commands)} hidden commands • Owner only"
            )

    await ctx.send(embed=embed)
