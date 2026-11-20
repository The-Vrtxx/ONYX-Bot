
"""ONYX secret achievement tracker.

Secret achievements are tracked in the background.
Members discover and view them on the ONYX website.
No secret achievement commands are exposed in Discord.
"""

import random
import time

from discord.ext import commands

from cogs.achievements.secret_definitions import SECRET_ACHIEVEMENTS


ACHIEVEMENTS_URL = "https://onyxdiscord.com/achievements/"


async def unlock_secret(bot, user, secret_id, guild=None, source="discovery"):
    """Unlock a secret achievement without announcing its details in Discord."""
    definition = SECRET_ACHIEVEMENTS.get(secret_id)
    if not definition:
        return False

    inserted = await bot.db.fetchone(
        """
        INSERT INTO onyx_achievement_secret_unlocks
            (user_id, secret_id, source)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, secret_id) DO NOTHING
        RETURNING secret_id
        """,
        (user.id, secret_id, source),
    )

    if not inserted:
        return False

    # Preserve the existing title reward.
    await bot.db.execute(
        """
        INSERT INTO onyx_achievement_titles
            (user_id, title, source_achievement)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, title) DO NOTHING
        """,
        (user.id, definition["title"], "secret:" + secret_id),
    )

    # Private website notification only. Never reveal the secret here.
    try:
        await user.send(
            "🏆 **You unlocked an ONYX achievement!**\n"
            "A secret achievement has been added to your collection.\n\n"
            f"View it on the ONYX website:\n{ACHIEVEMENTS_URL}"
        )
    except Exception:
        # Keep the unlock and title even when DMs are disabled.
        pass

    return True


async def secret_event(bot, user, event, guild=None, command=None):
    """Evaluate background activity for secret achievement unlocks."""
    uid = user.id
    now = int(time.time())

    row = await bot.db.fetchone(
        """
        SELECT last_activity_at, last_command, repeat_count
        FROM onyx_achievement_secret_state
        WHERE user_id=?
        """,
        (uid,),
    )

    previous = dict(row) if row else {}
    last_activity = int(previous.get("last_activity_at") or 0)

    await bot.db.execute(
        """
        INSERT INTO onyx_achievement_secret_state
            (user_id, last_activity_at, last_command, repeat_count)
        VALUES (?, ?, ?, 0)
        ON CONFLICT(user_id) DO UPDATE SET
            last_activity_at=excluded.last_activity_at
        """,
        (uid, now, command),
    )

    if last_activity and now - last_activity >= 30 * 86400:
        await unlock_secret(bot, user, "the_long_game", guild)

    if (
        event == "message"
        and guild
        and guild.member_count
        and guild.member_count <= 10
    ):
        await unlock_secret(bot, user, "ghost", guild)

    if event == "command" and command:
        repeat_count = (
            int(previous.get("repeat_count") or 0) + 1
            if previous.get("last_command") == command
            else 1
        )

        await bot.db.execute(
            """
            UPDATE onyx_achievement_secret_state
            SET last_command=?, repeat_count=?
            WHERE user_id=?
            """,
            (command, repeat_count, uid),
        )

        if repeat_count >= 5:
            await unlock_secret(bot, user, "deja_vu", guild)

        hour = time.gmtime(now).tm_hour

        if hour < 4:
            await unlock_secret(bot, user, "midnight_club", guild)

        # Retained for compatibility with the existing secret trigger.
        if command == "secrets":
            await unlock_secret(bot, user, "behind_the_curtain", guild)

        if random.random() < 0.002:
            await unlock_secret(bot, user, "lucky_break", guild)

        if random.random() < 0.0005:
            await unlock_secret(bot, user, "the_chosen_one", guild)

        if random.random() < 0.00001:
            await unlock_secret(bot, user, "one_in_a_million", guild)


class Secrets(commands.Cog):
    """Background-only secret achievement extension."""

    def __init__(self, bot):
        self.bot = bot


async def setup(bot):
    from cogs.achievements.engine import ensure_tables

    await ensure_tables(bot.db)
    await bot.add_cog(Secrets(bot))
