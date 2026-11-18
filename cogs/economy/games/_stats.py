
"""Persistent ONYX Arcade round history and player statistics."""


async def ensure_arcade_stats_tables(pool):
    """Create arcade history storage without changing existing economy data."""

    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS onyx_arcade_rounds (
                reference TEXT PRIMARY KEY,
                user_id BIGINT NOT NULL,
                game TEXT NOT NULL,
                wager BIGINT NOT NULL DEFAULT 0,
                outcome TEXT NOT NULL,
                payout BIGINT NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CHECK (wager >= 0),
                CHECK (payout >= 0),
                CHECK (outcome IN ('win', 'loss', 'push', 'challenge'))
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_onyx_arcade_rounds_user_time
            ON onyx_arcade_rounds(user_id, created_at DESC)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_onyx_arcade_rounds_game_time
            ON onyx_arcade_rounds(game, created_at DESC)
        """)


async def record_arcade_round(
    pool,
    reference,
    user_id,
    game,
    wager,
    outcome,
    payout=0,
):
    """Record a settled round once; duplicate callbacks cannot duplicate stats."""

    reference = str(reference).strip()
    game = str(game).strip().casefold()
    outcome = str(outcome).strip().casefold()
    user_id = int(user_id)
    wager = int(wager)
    payout = int(payout)

    if not reference or len(reference) > 160:
        raise ValueError("Invalid arcade round reference.")

    if not game or len(game) > 32:
        raise ValueError("Invalid arcade game name.")

    if outcome not in {"win", "loss", "push", "challenge"}:
        raise ValueError("Invalid arcade outcome.")

    if wager < 0 or payout < 0:
        raise ValueError("Wager and payout cannot be negative.")

    async with pool.acquire() as conn:
        result = await conn.execute("""
            INSERT INTO onyx_arcade_rounds (
                reference, user_id, game, wager, outcome, payout
            )
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (reference) DO NOTHING
        """, reference, user_id, game, wager, outcome, payout)

    return result.endswith("1")


async def get_player_arcade_stats(pool, user_id):
    """Return aggregate arcade statistics for one player."""

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT
                COUNT(*)::BIGINT AS games_played,
                COUNT(*) FILTER (WHERE outcome='win')::BIGINT AS wins,
                COUNT(*) FILTER (WHERE outcome='loss')::BIGINT AS losses,
                COUNT(*) FILTER (WHERE outcome='push')::BIGINT AS pushes,
                COALESCE(SUM(wager), 0)::BIGINT AS total_wagered,
                COALESCE(SUM(payout), 0)::BIGINT AS total_returned,
                COALESCE(MAX(payout), 0)::BIGINT AS biggest_return
            FROM onyx_arcade_rounds
            WHERE user_id=$1
        """, int(user_id))

    return dict(row)


async def get_recent_arcade_rounds(pool, user_id, limit=10):
    """Return a player's most recent settled arcade rounds."""

    limit = max(1, min(int(limit), 25))

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT game, wager, outcome, payout, created_at
            FROM onyx_arcade_rounds
            WHERE user_id=$1
            ORDER BY created_at DESC
            LIMIT $2
        """, int(user_id), limit)

    return [dict(row) for row in rows]


async def get_arcade_leaderboard(pool, limit=10):
    """Rank players by total arcade returns, then wins."""

    limit = max(1, min(int(limit), 25))

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                user_id,
                COUNT(*)::BIGINT AS games_played,
                COUNT(*) FILTER (WHERE outcome='win')::BIGINT AS wins,
                COALESCE(SUM(payout), 0)::BIGINT AS total_returned
            FROM onyx_arcade_rounds
            GROUP BY user_id
            ORDER BY total_returned DESC, wins DESC, user_id ASC
            LIMIT $1
        """, limit)

    return [dict(row) for row in rows]
