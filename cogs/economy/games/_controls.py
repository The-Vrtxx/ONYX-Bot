
"""ONYX Arcade runtime controls.

Reads global arcade settings configured through the owner website.
Settings are checked when a new game or streak round begins.
"""

import json


DEFAULT_CONFIG = {
    "enabled": True,
    "games": {
        "blackjack": True,
        "slots": True,
        "dice": True,
        "betflip": True,
        "mines": True,
        "roulette": True,
        "crash": True,
    },
    "streaks_enabled": True,
    "minimum_wager": 1,
    "maximum_wager": 1_000_000,
    "maximum_payout": 2_000_000,
    "maximum_streak_wins": 10,
}


async def ensure_arcade_control_tables(pool):
    """Ensure the website-controlled arcade settings table exists."""

    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS onyx_arcade_control (
                id INTEGER PRIMARY KEY CHECK (id=1),
                config JSONB NOT NULL DEFAULT '{}'::jsonb,
                updated_by BIGINT,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await conn.execute("""
            INSERT INTO onyx_arcade_control (id, config)
            VALUES (1, $1::jsonb)
            ON CONFLICT (id) DO NOTHING
        """, json.dumps(DEFAULT_CONFIG))


def normalize_config(raw):
    """Return a complete, validated configuration."""

    try:
        if isinstance(raw, dict):
            stored = dict(raw)
        else:
            stored = json.loads(raw or "{}")
    except (TypeError, ValueError):
        stored = {}

    config = dict(DEFAULT_CONFIG)

    for key in (
        "enabled",
        "streaks_enabled",
        "minimum_wager",
        "maximum_wager",
        "maximum_payout",
        "maximum_streak_wins",
    ):
        if key in stored:
            config[key] = stored[key]

    stored_games = stored.get("games", {})

    config["games"] = {
        game: (
            stored_games.get(game, True)
            if isinstance(stored_games, dict)
            else True
        )
        for game in DEFAULT_CONFIG["games"]
    }

    return config


async def get_arcade_config(bot):
    """Retrieve the latest arcade settings from PostgreSQL."""

    if getattr(bot.db, "backend", None) != "postgres":
        return dict(DEFAULT_CONFIG)

    pool = bot.db.pool

    await ensure_arcade_control_tables(pool)

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT config
            FROM onyx_arcade_control
            WHERE id=1
        """)

    if not row:
        return dict(DEFAULT_CONFIG)

    return normalize_config(row["config"])


async def game_is_enabled(bot, game):
    """Check whether a particular game can accept new rounds."""

    config = await get_arcade_config(bot)

    game = str(game).casefold()

    if not config["enabled"]:
        return False

    return bool(config["games"].get(game, False))


async def streaks_are_enabled(bot):
    """Check whether players can start or continue streaks."""

    config = await get_arcade_config(bot)

    return bool(
        config["enabled"]
        and config["streaks_enabled"]
    )


async def validate_wager(bot, amount):
    """Validate a new wager against website-controlled limits."""

    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return {
            "ok": False,
            "error": "Enter a valid wager amount.",
        }

    config = await get_arcade_config(bot)

    if not config["enabled"]:
        return {
            "ok": False,
            "error": "The ONYX Arcade is currently disabled.",
        }

    minimum = int(config["minimum_wager"])
    maximum = int(config["maximum_wager"])

    if amount < minimum or amount > maximum:
        return {
            "ok": False,
            "error": (
                f"Arcade wagers must be between "
                f"{minimum:,} and {maximum:,} Credits."
            ),
        }

    return {
        "ok": True,
        "amount": amount,
        "config": config,
    }
