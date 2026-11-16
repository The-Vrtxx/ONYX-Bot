
"""ONYX arcade streak engine.

A streak keeps its winnings in PostgreSQL until the player cashes out.
The entire current pot is risked on the next game.
"""

import uuid

from currency_system import MAX_CREDITS, grant_credits


async def ensure_streak_tables(pool):
    """Create the persistent arcade streak table."""

    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS onyx_arcade_streaks (
                user_id BIGINT PRIMARY KEY,
                streak_id TEXT NOT NULL,
                pot BIGINT NOT NULL,
                streak_wins INTEGER NOT NULL DEFAULT 1,
                next_multiplier INTEGER NOT NULL DEFAULT 3,
                status TEXT NOT NULL DEFAULT 'active',
                current_game TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CHECK (pot >= 0),
                CHECK (streak_wins >= 1),
                CHECK (next_multiplier >= 3),
                CHECK (status IN ('active', 'playing', 'cashed_out', 'lost'))
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_onyx_arcade_streak_status
            ON onyx_arcade_streaks(status, updated_at DESC)
        """)


async def get_streak(bot, user_id):
    """Return a player's active streak, if one exists."""

    async with bot.db.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT *
            FROM onyx_arcade_streaks
            WHERE user_id=$1
              AND status IN ('active', 'playing')
        """, int(user_id))

    return dict(row) if row else None


async def create_streak(bot, user_id, initial_pot, game, reference=None):
    """Create a streak after a player's first game win."""

    user_id = int(user_id)
    initial_pot = int(initial_pot)

    if initial_pot <= 0 or initial_pot > MAX_CREDITS:
        return {
            "ok": False,
            "error": "That winning amount is outside the Credits limit.",
        }

    streak_id = str(reference or uuid.uuid4().hex)

    async with bot.db.pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("""
                INSERT INTO onyx_arcade_streaks (
                    user_id,
                    streak_id,
                    pot,
                    streak_wins,
                    next_multiplier,
                    status,
                    current_game
                )
                VALUES ($1, $2, $3, 1, 3, 'active', $4)
                ON CONFLICT (user_id) DO UPDATE
                SET streak_id=EXCLUDED.streak_id,
                    pot=EXCLUDED.pot,
                    streak_wins=1,
                    next_multiplier=3,
                    status='active',
                    current_game=EXCLUDED.current_game,
                    created_at=CURRENT_TIMESTAMP,
                    updated_at=CURRENT_TIMESTAMP
                WHERE onyx_arcade_streaks.status
                    IN ('cashed_out', 'lost')
                RETURNING *
            """, user_id, streak_id, initial_pot, str(game)[:32])

            if row is None:
                return {
                    "ok": False,
                    "error": "You already have an active arcade streak.",
                }

            return {
                "ok": True,
                "streak": dict(row),
            }


async def begin_streak_round(bot, user_id, game):
    """Lock an active streak while the player plays the next game."""

    async with bot.db.pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("""
                SELECT *
                FROM onyx_arcade_streaks
                WHERE user_id=$1
                FOR UPDATE
            """, int(user_id))

            if not row or row["status"] != "active":
                return {
                    "ok": False,
                    "error": "You do not have a streak ready to continue.",
                }

            await conn.execute("""
                UPDATE onyx_arcade_streaks
                SET status='playing',
                    current_game=$2,
                    updated_at=CURRENT_TIMESTAMP
                WHERE user_id=$1
            """, int(user_id), str(game)[:32])

            return {
                "ok": True,
                "streak_id": row["streak_id"],
                "wager": int(row["pot"]),
                "streak_wins": int(row["streak_wins"]),
                "multiplier": int(row["next_multiplier"]),
                "game": str(game),
            }


async def record_streak_win(bot, user_id, streak_id):
    """Increase the streak pot after a successful continued round."""

    user_id = int(user_id)

    async with bot.db.pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("""
                SELECT *
                FROM onyx_arcade_streaks
                WHERE user_id=$1
                FOR UPDATE
            """, user_id)

            if (
                not row
                or row["status"] != "playing"
                or row["streak_id"] != str(streak_id)
            ):
                return {
                    "ok": False,
                    "error": "This streak round is no longer active.",
                }

            old_pot = int(row["pot"])
            multiplier = int(row["next_multiplier"])
            new_pot = old_pot * multiplier

            if new_pot > MAX_CREDITS:
                return {
                    "ok": False,
                    "error": (
                        "The next streak payout would exceed "
                        "the maximum Credits limit. Cash out your "
                        "current streak instead."
                    ),
                    "streak": dict(row),
                }

            updated = await conn.fetchrow("""
                UPDATE onyx_arcade_streaks
                SET pot=$2,
                    streak_wins=streak_wins+1,
                    next_multiplier=next_multiplier+1,
                    status='active',
                    current_game=NULL,
                    updated_at=CURRENT_TIMESTAMP
                WHERE user_id=$1
                RETURNING *
            """, user_id, new_pot)

            return {
                "ok": True,
                "streak": dict(updated),
                "previous_pot": old_pot,
                "multiplier_used": multiplier,
                "new_pot": new_pot,
            }


async def lose_streak(bot, user_id, streak_id):
    """End a streak after the player loses a continued round."""

    async with bot.db.pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("""
                SELECT *
                FROM onyx_arcade_streaks
                WHERE user_id=$1
                FOR UPDATE
            """, int(user_id))

            if (
                not row
                or row["status"] != "playing"
                or row["streak_id"] != str(streak_id)
            ):
                return {
                    "ok": False,
                    "error": "This streak round is no longer active.",
                }

            await conn.execute("""
                UPDATE onyx_arcade_streaks
                SET status='lost',
                    current_game=NULL,
                    updated_at=CURRENT_TIMESTAMP
                WHERE user_id=$1
            """, int(user_id))

            return {
                "ok": True,
                "lost_amount": int(row["pot"]),
                "streak_wins": int(row["streak_wins"]),
            }


async def cancel_streak_round(bot, user_id, streak_id):
    """Return an unfinished round to the active state.

    This does not award or remove Credits. The pot remains in escrow.
    """

    async with bot.db.pool.acquire() as conn:
        async with conn.transaction():
            result = await conn.execute("""
                UPDATE onyx_arcade_streaks
                SET status='active',
                    current_game=NULL,
                    updated_at=CURRENT_TIMESTAMP
                WHERE user_id=$1
                  AND streak_id=$2
                  AND status='playing'
            """, int(user_id), str(streak_id))

    return result.endswith("1")


async def cash_out_streak(bot, user_id):
    """Transfer the current streak pot to the player's Credits wallet."""

    user_id = int(user_id)

    async with bot.db.pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("""
                SELECT *
                FROM onyx_arcade_streaks
                WHERE user_id=$1
                FOR UPDATE
            """, user_id)

            if not row or row["status"] != "active":
                return {
                    "ok": False,
                    "error": "There is no streak ready to cash out.",
                }

            amount = int(row["pot"])
            reference = f"{row['streak_id']}:cashout"

            try:
                payout = await grant_credits(
                    conn,
                    user_id,
                    amount,
                    source="arcade_streak",
                    description="ONYX arcade streak cashout",
                    reference_id=reference,
                )
            except ValueError as error:
                return {
                    "ok": False,
                    "error": str(error),
                }

            if not payout.get("ok"):
                return {
                    "ok": False,
                    "error": "This streak payout was already processed.",
                }

            await conn.execute("""
                UPDATE onyx_arcade_streaks
                SET status='cashed_out',
                    current_game=NULL,
                    updated_at=CURRENT_TIMESTAMP
                WHERE user_id=$1
            """, user_id)

            return {
                "ok": True,
                "amount": amount,
                "streak_wins": int(row["streak_wins"]),
                "credits": int(payout["credits"]),
            }
