import discord
from discord.ext import commands


# Canonical command path -> ONYX shortcuts.
# main.py translates these shortcuts before discord.py processes messages.
#
# Only include commands that exist in the current cog source.
# Built-in discord.py aliases are intentionally left to their own commands.

COMMAND_ALIASES = {
    # ─────────────────────────────
    # Core / utility
    # ─────────────────────────────
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

    # ─────────────────────────────
    # Moderation
    # ─────────────────────────────
    "ban": ["b"],
    "kick": ["k"],
    "timeout": ["to"],
    "untimeout": ["uto"],
    "warn": ["w"],
    "warnings": ["ws"],
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

    # Additional moderation
    "mute": ["mt"],
    "imute": ["imt"],
    "rmute": ["rmt"],
    "unmute": ["umt"],
    "unimute": ["uimt"],
    "unrmute": ["urmt"],
    "setupmute": ["smute"],
    "updatepermissions": ["uperm"],

    # ─────────────────────────────
    # Jail / security
    # ─────────────────────────────
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
    "antinuke staffrole add": ["ansra"],
    "antinuke staffrole remove": ["ansrr"],
    "antinuke whitelist": ["anw"],
    "antinuke whitelist add": ["anwa"],
    "antinuke whitelist remove": ["anwr"],
    "antinuke whitelist list": ["anwl"],
    "antinuke on": ["anon"],
    "antinuke off": ["anoff"],
    "antinuke logs": ["anlogs"],

    "automod": ["am"],
    "automod filter": ["amf"],
    "antiraid": ["ar"],
    "antiraid_off": ["aroff"],
    "honeypot": ["hp"],
    "honeypot create": ["hpc"],
    "honeypot status": ["hps"],
    "honeypot delete": ["hpd"],
    "security_set": ["secset"],
    "security_off": ["secoff"],

    # ─────────────────────────────
    # Channels / server
    # ─────────────────────────────
    "channel": ["ch"],
    "nuke": ["nk"],
    "channelcount": ["cc"],
    "rolelist": ["rl"],
    "emoji_list": ["el"],
    "permissions": ["perms"],
    "roleinfo": ["ri"],
    "servericon": ["icon"],
    "membercount": ["mcnt"],
    "firstmessage": ["fm"],
    "snipe": ["sn"],
    "editsnipe": ["esn"],

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
    "setup jail": ["sjail"],
    "settings": ["cfg"],
    "serverdata": ["sd"],

    "clearbots": ["cb"],
    "massrole": ["mr"],
    "backup": ["bk"],
    "backup create": ["bkcreate"],
    "backup restore": ["bkrestore"],

    # Server access / management
    "access": ["acc"],
    "allow": ["allowserver"],
    "revoke": ["revokeserver"],
    "manager": ["mgr"],
    "manager add": ["mgra"],
    "manager remove": ["mgrr"],
    "managers": ["mgrs"],
    "audit": ["auditservers"],
    "enforce": ["enforcewl"],

    # ─────────────────────────────
    # Administration / owner tools
    # ─────────────────────────────
    "developer": ["devteam"],
    "developer add": ["deva"],
    "developer remove": ["devr"],
    "developer list": ["devl"],
    "developer check": ["devc"],
    "stresstest": ["stress"],

    "shh": ["sh"],
    "shh_whitelist_add": ["shwa"],
    "shh_whitelist_remove": ["shwr"],
    "shh_set_role": ["shsr"],

    # ─────────────────────────────
    # Logging / welcome / engagement
    # ─────────────────────────────
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

    # ─────────────────────────────
    # Levels / prestige
    # ─────────────────────────────
    "rank": ["rnk"],
    "leaderboard": ["lb", "top"],
    "prestige": ["prest"],
    "prestige leaderboard": ["prestlb"],

    # Owner level administration
    "leveladmin": ["lvla"],
    "leveladmin xp": ["lvlxp"],
    "leveladmin xp add": ["lvladd"],
    "leveladmin xp set": ["lvlset"],
    "leveladmin xp remove": ["lvlrm"],
    "leveladmin reset": ["lvlreset"],

    # ─────────────────────────────
    # Fun
    # ─────────────────────────────
    "8ball": ["8b"],
    "coinflip": ["cf"],
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
    "number": ["num"],
    "riddle": ["rdl"],
    "truth": ["trth"],
    "dare": ["dr"],
    "emojify": ["em"],
    "mock": ["mk"],
    "reverse": ["rev"],
    "clap": ["cl"],
    "wyrvote": ["wv"],
    "pick": ["pickone"],
    "quote": ["qt"],

    # ─────────────────────────────
    # Custom commands / embeds
    # ─────────────────────────────
    "embed": ["emb"],
    "embed create": ["embc"],
    "copyembed": ["embcopy"],
    "custom_add": ["ca"],
    "custom_run": ["cr"],
    "custom_remove": ["crm"],

    # ─────────────────────────────
    # Giveaways
    # ─────────────────────────────
    "giveaway": ["gw"],
    "reroll": ["gr"],

    # ─────────────────────────────
    # Reports / tickets
    # ─────────────────────────────
    "setupreport": ["rsetup"],
    "setupcentralreports": ["rcsetup"],
    "report": ["rep"],

    "ticket_setup": ["tsetup"],
    "claim": ["tclaim"],
    "unclaim": ["tunclaim"],

    "ticket": ["t"],
    "ticket claim": ["tc"],
    "ticket unclaim": ["tuc"],
    "ticket add": ["ta"],
    "ticket remove": ["trm"],
    "ticket rename": ["tren"],
    "ticket priority": ["tprio"],
    "ticket transfer": ["txfer"],
    "ticket info": ["tinfo"],
    "ticket list": ["tl"],
    "ticket close": ["tclose"],
    "ticket category": ["tcat"],
    "ticket reopen": ["treopen"],

    # ─────────────────────────────
    # Voice
    # ─────────────────────────────
    "voicemaster_setup": ["vms"],

    # ─────────────────────────────
    # Last.fm
    # ─────────────────────────────
    "lastfm": ["lfm"],
    "lastfm connect": ["lfmc"],
    "lastfm finish": ["lfmf"],
    "lastfm logout": ["lfmo"],
    "lastfm account": ["lfma"],
    "lastfm status": ["lfmst"],
    "lastfm link": ["lfml"],
    "lastfm nowplaying": ["np"],
    "lastfm recent": ["lfmr"],
    "lastfm toptracks": ["tt"],
    "lastfm topartists": ["tart"],
    "lastfm topalbums": ["tal"],
    "lastfm profile": ["lfmp"],
    "lastfm artist": ["lfa"],
    "lastfm album": ["lfalb"],
    "lastfm track": ["lft"],
    "lastfm compare": ["lfmcx"],
}


class CommandAliases(commands.Cog):
    """Displays configured ONYX command shortcuts."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(
        name="aliases",
        aliases=["als"],
        help="Show ONYX command abbreviations.",
        hidden=True,
    )
    async def aliases(self, ctx, *, search: str = None):
        rows = []

        for command_path, short_names in COMMAND_ALIASES.items():
            command = self.bot.get_command(command_path)

            # Only show commands that are actually registered.
            if command is None:
                continue

            if search:
                term = search.casefold()
                if (
                    term not in command_path.casefold()
                    and not any(term in name.casefold() for name in short_names)
                ):
                    continue

            rows.append(
                f"`{ctx.prefix}{command_path}` → "
                + ", ".join(f"`{ctx.prefix}{name}`" for name in short_names)
            )

        if not rows:
            return await ctx.send(
                "No matching command abbreviations were found."
            )

        pages = [
            rows[index:index + 12]
            for index in range(0, len(rows), 12)
        ]

        current = 0

        def make_embed(index):
            embed = discord.Embed(
                title="ONYX • Command Abbreviations",
                description="\n".join(pages[index]),
                color=discord.Color.from_rgb(44, 38, 67),
            )
            embed.set_footer(
                text=(
                    f"{len(rows)} command entries • "
                    f"Page {index + 1}/{len(pages)} • "
                    "Use ,aliases <name> to search"
                )
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
                    "reaction_add",
                    timeout=90,
                    check=check,
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
