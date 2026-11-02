import discord
from discord.ext import commands


# Alias -> existing registered command path.
# Aliases point to the original command, preserving its checks,
# permissions, cooldowns, and callback.
COMMAND_ALIASES = {
    # Core / utility
    "help": ["h", "cmds"],
    "ping": ["pi"],
    "userinfo": ["ui", "whois"],
    "serverinfo": ["si", "guildinfo"],
    "botinfo": ["bi"],
    "avatar": ["av", "pfp"],
    "prefix": ["pr"],
    "prefix show": ["prshow"],
    "prefix set": ["prset"],
    "prefix reset": ["prreset"],

    # Moderation
    "ban": ["b"],
    "kick": ["k"],
    "timeout": ["to"],
    "untimeout": ["uto", "untime"],
    "warn": ["w"],
    "warnings": ["ws", "warns"],
    "purge": ["p", "clear"],
    "modlogs": ["ml", "history"],
    "case": ["mc"],
    "warn_escalation": ["we"],
    "lock": ["lk"],
    "unlock": ["ul"],
    "slowmode": ["sm"],
    "modnote": ["mn"],
    "modnotes": ["mns"],
    "nick": ["n"],
    "role_add": ["ra"],
    "role_remove": ["rr"],

    # Jail / protection / security
    "jail": ["j"],
    "jailtime": ["jt"],
    "unjail": ["uj"],
    "jaillist": ["jl"],
    "jailinfo": ["ji"],
    "jailcancel": ["jc"],
    "antinuke": ["an"],
    "antinuke help": ["anh"],
    "antinuke setup": ["ans"],
    "antinuke status": ["anst"],
    "antinuke threshold": ["ant"],
    "antinuke punishment": ["anp"],
    "antinuke logchannel": ["anlog"],
    "antinuke jailrole": ["anjr"],
    "antinuke staffrole": ["ansr"],
    "antinuke whitelist": ["anw"],
    "antinuke on": ["anon"],
    "antinuke off": ["anoff"],
    "antinuke logs": ["anlogs"],
    "automod": ["am"],
    "automod_ignore": ["ami"],
    "security_set": ["secset"],
    "security_off": ["secoff"],

    # Channels / server
    "channel": ["ch"],
    "create": ["cnew"],
    "create_channel": ["cadd"],
    "delete_channel": ["cdel"],
    "nuke": ["nk"],
    "channelcount": ["cc"],
    "rolelist": ["rl"],
    "emoji_list": ["el"],
    "permissions": ["perms"],
    "roleinfo": ["ri"],
    "servericon": ["icon"],
    "membercount": ["mcnt"],
    "firstmessage": ["fm"],
    "role_create": ["rc"],
    "role_delete": ["rd"],
    "role": ["r"],
    "rolepanel_create": ["rpc"],
    "autorole_set": ["ars"],
    "autorole_remove": ["arr"],
    "autorole_list": ["arl"],
    "reactionrole_add": ["rra"],
    "reactionrole_remove": ["rrr"],
    "reactionrole_list": ["rrl"],
    "selfrole_add": ["sra"],
    "selfrole_remove": ["srr"],
    "selfrole_list": ["srl"],
    "setup": ["ss"],
    "settings": ["cfg"],
    "serverdata": ["sd"],
    "shh_whitelist_add": ["shwa"],
    "shh_whitelist_remove": ["shwr"],
    "shh_set_role": ["shsr"],

    # Logging / welcome / engagement
    "logging_set": ["logs"],
    "logging_remove": ["logr"],
    "logging_list": ["logl"],
    "logging_test": ["logt"],
    "welcome_set": ["wset"],
    "goodbye_set": ["gset"],
    "poll": ["pl"],
    "autoresponse_add": ["ara"],
    "autoresponse_remove": ["arrm"],
    "autoresponse_list": ["arlst"],

    # Levels / fun
    "rank": ["rnk"],
    "leaderboard": ["lb", "top"],
    "levels_settings": ["lvls"],
    "8ball": ["8b", "eightball"],
    "coinflip": ["cf", "flip"],
    "roll": ["dice"],
    "choose": ["chz"],
    "rate": ["rt"],
    "joke": ["jk"],
    "fact": ["fc"],
    "wouldyourather": ["wyr"],
    "trivia": ["tr"],
    "rps": ["rpsls"],
    "teamup": ["tu"],
    "ship": ["duo"],
    "compliment": ["comp"],
    "roast": ["ro"],
    "meme": ["mm"],
    "fortune": ["fort"],
    "number": ["num", "rng"],
    "riddle": ["rdl"],
    "truth": ["trth"],
    "dare": ["dr"],
    "emojify": ["em"],
    "mock": ["mk"],
    "reverse": ["rev"],
    "clap": ["cl"],
    "wyrvote": ["wv"],
    "pick": ["pickone"],

    # Custom commands / embeds / tickets / voice
    "embed": ["emb"],
    "custom_add": ["ca"],
    "custom_run": ["cr"],
    "custom_remove": ["crm"],
    "embed_template_save": ["ets"],
    "embed_template_send": ["etp"],
    "embed_template_delete": ["etd"],
    "ticket_setup": ["tsetup"],
    "voicemaster_setup": ["vms"],

    # Last.fm
    "lastfm": ["lfm", "fm"],
    "lastfm connect": ["lfmc"],
    "lastfm finish": ["lfmf"],
    "lastfm logout": ["lfmo"],
    "lastfm account": ["lfma"],
    "lastfm status": ["lfmst"],
    "lastfm link": ["lfml"],
    "lastfm nowplaying": ["np", "now"],
    "lastfm recent": ["rec"],
    "lastfm toptracks": ["tt"],
    "lastfm topartists": ["ta"],
    "lastfm topalbums": ["tal"],
    "lastfm profile": ["lfmp"],
    "lastfm artist": ["lfa"],
    "lastfm album": ["lfalb"],
    "lastfm track": ["lft"],
    "lastfm compare": ["lfmcx"],
}


class CommandAliases(commands.Cog):
    """Registers short aliases for ONYX's existing prefix commands."""

    def __init__(self, bot):
        self.bot = bot
        self.applied = False
        self.applied_count = 0
        self.skipped = []

    @commands.Cog.listener()
    async def on_ready(self):
        # Commands from every extension are loaded in setup_hook before on_ready.
        # Re-run safely after reconnects/reloads; do not duplicate aliases.
        self.apply_aliases()

    def apply_aliases(self):
        self.applied_count = 0
        self.skipped = []

        for command_path, aliases in COMMAND_ALIASES.items():
            command = self.bot.get_command(command_path)
            if command is None:
                self.skipped.append(f"{command_path} (command not found)")
                continue

            namespace = command.parent
            registry = namespace.all_commands if namespace else self.bot.all_commands

            for raw_alias in aliases:
                alias = raw_alias.strip().lower()
                if not alias or " " in alias:
                    continue

                existing = registry.get(alias)
                if existing is not None:
                    if existing is command:
                        if alias not in command.aliases:
                            command.aliases.append(alias)
                        continue
                    self.skipped.append(
                        f"{command_path} -> {alias} (already registered)"
                    )
                    continue

                # Critical: register the alias in discord.py's actual lookup
                # mapping. Updating command.aliases alone does not do this.
                registry[alias] = command
                if alias not in command.aliases:
                    command.aliases.append(alias)
                self.applied_count += 1

        self.applied = True

        # Log a useful summary in Render logs.
        import logging
        logger = logging.getLogger("bot.aliases")
        logger.info(
            "Command aliases registered: %s | skipped: %s",
            self.applied_count,
            len(self.skipped)
        )
        if self.skipped:
            logger.warning("Alias registration skipped: %s", "; ".join(self.skipped))

    @commands.command(
        name="aliases",
        aliases=["als"],
        help="Show ONYX command abbreviations.",
        hidden=True
    )
    async def aliases(self, ctx, *, search: str = None):
        rows = []
        for command_path, short_names in COMMAND_ALIASES.items():
            command = self.bot.get_command(command_path)
            if command is None:
                continue
            if search and search.casefold() not in command_path.casefold() and not any(
                search.casefold() in name.casefold() for name in short_names
            ):
                continue
            rows.append(
                f"`{ctx.prefix}{command_path}` → "
                + ", ".join(f"`{ctx.prefix}{name}`" for name in short_names)
            )

        if not rows:
            return await ctx.send("No matching command abbreviations were found.")

        pages = [rows[i:i + 12] for i in range(0, len(rows), 12)]
        current = 0

        def make_embed(index):
            embed = discord.Embed(
                title="ONYX • Command Abbreviations",
                description="\n".join(pages[index]),
                color=discord.Color.from_rgb(44, 38, 67)
            )
            embed.set_footer(
                text=f"{len(rows)} command entries • Page {index + 1}/{len(pages)} • Use ,aliases <name> to search"
            )
            return embed

        message = await ctx.send(embed=make_embed(current))
        if len(pages) <= 1:
            return

        for emoji in ("◀️", "▶️"):
            try:
                await message.add_reaction(emoji)
            except discord.HTTPException:
                return

        def check(reaction, user):
            return (
                user.id == ctx.author.id
                and reaction.message.id == message.id
                and str(reaction.emoji) in {"◀️", "▶️"}
            )

        while True:
            try:
                reaction, user = await self.bot.wait_for(
                    "reaction_add", timeout=90, check=check
                )
            except TimeoutError:
                break

            if str(reaction.emoji) == "▶️":
                current = min(len(pages) - 1, current + 1)
            else:
                current = max(0, current - 1)

            await message.edit(embed=make_embed(current))
            try:
                await message.remove_reaction(reaction, user)
            except discord.HTTPException:
                pass


async def setup(bot):
    await bot.add_cog(CommandAliases(bot))
