
"""ONYX global achievement engine.

Twenty permanent achievements across four tiers.
Progress is calculated from global arcade history.
Rewards are granted once per player and achievement.
"""

from currency_system import grant_credits


ACHIEVEMENTS = {
    # BRONZE
    "first_steps": {
        "name": "First Steps",
        "description": "Complete your first arcade game.",
        "tier": "Bronze",
        "icon": "🎮",
        "type": "games",
        "target": 1,
        "reward": 250,
    },
    "taste_of_victory": {
        "name": "Taste of Victory",
        "description": "Win your first arcade game.",
        "tier": "Bronze",
        "icon": "🥇",
        "type": "wins",
        "target": 1,
        "reward": 500,
    },
    "regular_player": {
        "name": "Regular Player",
        "description": "Complete 10 arcade games.",
        "tier": "Bronze",
        "icon": "🕹️",
        "type": "games",
        "target": 10,
        "reward": 1000,
    },
    "variety_player": {
        "name": "Variety Player",
        "description": "Play 3 different casino games.",
        "tier": "Bronze",
        "icon": "🎲",
        "type": "different_games",
        "target": 3,
        "reward": 1000,
    },
    "first_fortune": {
        "name": "First Fortune",
        "description": "Receive a return of 5,000 Credits or more.",
        "tier": "Bronze",
        "icon": "💰",
        "type": "biggest_return",
        "target": 5000,
        "reward": 1000,
    },

    # SILVER
    "arcade_veteran": {
        "name": "Arcade Veteran",
        "description": "Complete 100 arcade games.",
        "tier": "Silver",
        "icon": "🏆",
        "type": "games",
        "target": 100,
        "reward": 5000,
    },
    "winning_habit": {
        "name": "Winning Habit",
        "description": "Win 25 arcade games.",
        "tier": "Silver",
        "icon": "🌟",
        "type": "wins",
        "target": 25,
        "reward": 2500,
    },
    "high_roller": {
        "name": "High Roller",
        "description": "Wager 100,000 Credits cumulatively.",
        "tier": "Silver",
        "icon": "💎",
        "type": "wagered",
        "target": 100_000,
        "reward": 2500,
    },
    "game_collector": {
        "name": "Game Collector",
        "description": "Play all 8 casino games.",
        "tier": "Silver",
        "icon": "🎯",
        "type": "different_games",
        "target": 8,
        "reward": 5000,
    },
    "big_payday": {
        "name": "Big Payday",
        "description": "Receive a return of 50,000 Credits or more.",
        "tier": "Silver",
        "icon": "💵",
        "type": "biggest_return",
        "target": 50_000,
        "reward": 5000,
    },

    # GOLD
    "arcade_legend": {
        "name": "Arcade Legend",
        "description": "Complete 500 arcade games.",
        "tier": "Gold",
        "icon": "👑",
        "type": "games",
        "target": 500,
        "reward": 15_000,
    },
    "unstoppable": {
        "name": "Unstoppable",
        "description": "Win 100 arcade games.",
        "tier": "Gold",
        "icon": "🔥",
        "type": "wins",
        "target": 100,
        "reward": 15_000,
    },
    "millionaire_gambler": {
        "name": "Millionaire Gambler",
        "description": "Wager 1,000,000 Credits cumulatively.",
        "tier": "Gold",
        "icon": "💠",
        "type": "wagered",
        "target": 1_000_000,
        "reward": 10_000,
    },
    "master_collector": {
        "name": "Master Collector",
        "description": "Win at least once in all 8 casino games.",
        "tier": "Gold",
        "icon": "🏅",
        "type": "games_won",
        "target": 8,
        "reward": 20_000,
    },
    "massive_payday": {
        "name": "Massive Payday",
        "description": "Receive a return of 250,000 Credits or more.",
        "tier": "Gold",
        "icon": "💸",
        "type": "biggest_return",
        "target": 250_000,
        "reward": 25_000,
    },

    # DIAMOND
    "onyx_immortal": {
        "name": "ONYX Immortal",
        "description": "Complete 2,500 arcade games.",
        "tier": "Diamond",
        "icon": "⚜️",
        "type": "games",
        "target": 2500,
        "reward": 50_000,
    },
    "perfect_dedication": {
        "name": "Perfect Dedication",
        "description": "Win 500 arcade games.",
        "tier": "Diamond",
        "icon": "💫",
        "type": "wins",
        "target": 500,
        "reward": 50_000,
    },
    "billionaires_path": {
        "name": "Billionaire's Path",
        "description": "Wager 10,000,000 Credits cumulatively.",
        "tier": "Diamond",
        "icon": "💎",
        "type": "wagered",
        "target": 10_000_000,
        "reward": 75_000,
    },
    "ultimate_collector": {
        "name": "The Ultimate Collector",
        "description": "Win 100 times across all 8 casino games.",
        "tier": "Diamond",
        "icon": "🏆",
        "type": "wins",
        "target": 100,
        "reward": 100_000,
        "require_all_games": True,
    },
    "legendary_fortune": {
        "name": "Legendary Fortune",
        "description": "Receive a return of 1,000,000 Credits or more.",
        "tier": "Diamond",
        "icon": "🌌",
        "type": "biggest_return",
        "target": 1_000_000,
        "reward": 150_000,
    },
}


CASINO_GAMES = (
    "blackjack",
    "slots",
    "dice",
    "betflip",
    "mines",
    "roulette",
    "crash",
    "baccarat",
)


async def ensure_achievement_tables(pool):
    """Create global achievement storage."""

    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS onyx_achievements (
                achievement_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                reward BIGINT NOT NULL DEFAULT 0,
                tier TEXT NOT NULL DEFAULT 'Bronze',
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await conn.execute("""
            ALTER TABLE onyx_achievements
            ADD COLUMN IF NOT EXISTS tier TEXT NOT NULL DEFAULT 'Bronze'
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS onyx_user_achievements (
                user_id BIGINT NOT NULL,
                achievement_id TEXT NOT NULL
                    REFERENCES onyx_achievements(achievement_id),
                unlocked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reward_paid BIGINT NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, achievement_id),
                CHECK (reward_paid >= 0)
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS
                idx_onyx_user_achievements_user
            ON onyx_user_achievements(user_id, unlocked_at DESC)
        """)

        for achievement_id, achievement in ACHIEVEMENTS.items():
            await conn.execute("""
                INSERT INTO onyx_achievements (
                    achievement_id,
                    name,
                    description,
                    reward,
                    tier
                )
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (achievement_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    reward = EXCLUDED.reward,
                    tier = EXCLUDED.tier
            """,
                achievement_id,
                achievement["name"],
                achievement["description"],
                achievement["reward"],
                achievement["tier"],
            )


async def get_achievement_progress(pool, user_id):
    """Calculate a player's global achievement progress."""

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT
                COUNT(*)::BIGINT AS games,
                COUNT(*) FILTER (
                    WHERE outcome='win'
                )::BIGINT AS wins,
                COALESCE(SUM(wager), 0)::BIGINT AS wagered,
                COALESCE(MAX(payout), 0)::BIGINT AS biggest_return,
                COUNT(DISTINCT game)::BIGINT AS different_games,
                COUNT(DISTINCT game) FILTER (
                    WHERE outcome='win'
                )::BIGINT AS games_won
            FROM onyx_arcade_rounds
            WHERE user_id=$1
              AND game = ANY($2::TEXT[])
        """, int(user_id), list(CASINO_GAMES))

    return {
        "games": int(row["games"]),
        "wins": int(row["wins"]),
        "wagered": int(row["wagered"]),
        "biggest_return": int(row["biggest_return"]),
        "different_games": int(row["different_games"]),
        "games_won": int(row["games_won"]),
    }


async def get_unlocked_achievements(pool, user_id):
    """Return every achievement unlocked by a player."""

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                achievement_id,
                unlocked_at,
                reward_paid
            FROM onyx_user_achievements
            WHERE user_id=$1
            ORDER BY unlocked_at DESC
        """, int(user_id))

    return [dict(row) for row in rows]


async def evaluate_achievements(
    bot,
    user_id,
    display_name=None,
    username=None,
):
    """Unlock completed achievements and award their Credits once."""

    pool = bot.db.pool
    progress = await get_achievement_progress(pool, user_id)
    unlocked_now = []

    for achievement_id, achievement in ACHIEVEMENTS.items():
        progress_type = achievement["type"]
        current = progress[progress_type]
        target = int(achievement["target"])

        if current < target:
            continue

        if achievement.get("require_all_games"):
            if progress["games_won"] < len(CASINO_GAMES):
                continue

        reward = int(achievement["reward"])

        async with pool.acquire() as conn:
            async with conn.transaction():
                inserted = await conn.fetchrow("""
                    INSERT INTO onyx_user_achievements (
                        user_id,
                        achievement_id,
                        reward_paid
                    )
                    VALUES ($1, $2, $3)
                    ON CONFLICT (user_id, achievement_id)
                    DO NOTHING
                    RETURNING achievement_id
                """, int(user_id), achievement_id, reward)

                if not inserted:
                    continue

                paid = await grant_credits(
                    conn,
                    int(user_id),
                    reward,
                    source="achievement_reward",
                    description=(
                        f"ONYX Achievement: {achievement['name']}"
                    ),
                    reference_id=f"achievement:{achievement_id}",
                )

                if not paid.get("ok"):
                    raise RuntimeError(
                        "Achievement reward could not be processed."
                    )

                if display_name or username:
                    await conn.execute("""
                        INSERT INTO onyx_discord_user_profiles (
                            user_id,
                            display_name,
                            username,
                            updated_at
                        )
                        VALUES ($1, $2, $3, CURRENT_TIMESTAMP)
                        ON CONFLICT (user_id) DO UPDATE SET
                            display_name = COALESCE(
                                EXCLUDED.display_name,
                                onyx_discord_user_profiles.display_name
                            ),
                            username = COALESCE(
                                EXCLUDED.username,
                                onyx_discord_user_profiles.username
                            ),
                            updated_at = CURRENT_TIMESTAMP
                    """,
                        int(user_id),
                        display_name,
                        username,
                    )

        unlocked_now.append({
            "id": achievement_id,
            "name": achievement["name"],
            "description": achievement["description"],
            "tier": achievement["tier"],
            "icon": achievement["icon"],
            "reward": reward,
        })

    return unlocked_now
