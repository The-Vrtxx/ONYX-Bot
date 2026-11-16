
"""ONYX dual-currency economy foundation.

Prestige Tokens remain in the existing onyx_prestige_wallet.
ONYX Credits use a separate wallet and transaction ledger.
"""

MAX_CREDITS = 2_000_000_000


async def ensure_currency_tables(pool):
    """Create ONYX Credits tables and Discord identity records."""

    await pool.execute("""
        CREATE TABLE IF NOT EXISTS onyx_credit_wallet (
            user_id BIGINT PRIMARY KEY,
            credits BIGINT NOT NULL DEFAULT 0,
            lifetime_earned BIGINT NOT NULL DEFAULT 0,
            lifetime_spent BIGINT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (credits >= 0),
            CHECK (lifetime_earned >= 0),
            CHECK (lifetime_spent >= 0)
        )
    """)

    await pool.execute("""
        CREATE TABLE IF NOT EXISTS onyx_credit_transactions (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            amount BIGINT NOT NULL,
            balance_after BIGINT NOT NULL,
            transaction_type TEXT NOT NULL,
            source TEXT NOT NULL,
            reference_id TEXT,
            description TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (amount <> 0),
            CHECK (balance_after >= 0)
        )
    """)

    await pool.execute("""
        CREATE INDEX IF NOT EXISTS idx_onyx_credit_transactions_user
        ON onyx_credit_transactions(user_id, created_at DESC)
    """)

    await pool.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_onyx_credit_transactions_reference
        ON onyx_credit_transactions(user_id, source, reference_id)
        WHERE reference_id IS NOT NULL
    """)

    await pool.execute("""
        CREATE TABLE IF NOT EXISTS onyx_credit_claims (
            user_id BIGINT NOT NULL,
            claim_type TEXT NOT NULL,
            claim_date DATE NOT NULL,
            credits_awarded BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, claim_type, claim_date),
            CHECK (credits_awarded >= 0)
        )
    """)

    await pool.execute("""
        CREATE TABLE IF NOT EXISTS onyx_discord_user_profiles (
            user_id BIGINT PRIMARY KEY,
            display_name TEXT,
            username TEXT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    await pool.execute("""
        CREATE INDEX IF NOT EXISTS idx_onyx_discord_profiles_display_name
        ON onyx_discord_user_profiles(LOWER(display_name))
    """)


async def update_discord_user_profile(
    conn,
    user_id,
    display_name=None,
    username=None
):
    """Store the latest known global Discord display name."""

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
    """, user_id, display_name, username)


async def ensure_credit_wallet(conn, user_id):
    """Create a wallet if the member does not already have one."""

    await conn.execute("""
        INSERT INTO onyx_credit_wallet(user_id)
        VALUES($1)
        ON CONFLICT(user_id) DO NOTHING
    """, user_id)


async def get_credit_balance(conn, user_id):
    """Return the member's current ONYX Credits balance."""

    await ensure_credit_wallet(conn, user_id)

    row = await conn.fetchrow("""
        SELECT credits, lifetime_earned, lifetime_spent
        FROM onyx_credit_wallet
        WHERE user_id=$1
    """, user_id)

    return {
        "credits": int(row["credits"]),
        "lifetime_earned": int(row["lifetime_earned"]),
        "lifetime_spent": int(row["lifetime_spent"])
    }


async def grant_credits(
    conn,
    user_id,
    amount,
    source,
    description="",
    reference_id=None
):
    """Grant Credits safely and record the transaction.

    Call this inside an existing database transaction.
    A reference_id prevents the same reward from being granted
    twice for the same user and source.
    """

    amount = int(amount)

    if amount <= 0 or amount > MAX_CREDITS:
        raise ValueError("Credit reward must be a positive valid amount.")

    source = str(source).strip().lower()

    if not source or len(source) > 48:
        raise ValueError("A valid reward source is required.")

    if reference_id is not None:
        reference_id = str(reference_id).strip()

        if not reference_id or len(reference_id) > 120:
            raise ValueError("Invalid reward reference.")

    await ensure_credit_wallet(conn, user_id)

    wallet = await conn.fetchrow("""
        SELECT credits
        FROM onyx_credit_wallet
        WHERE user_id=$1
        FOR UPDATE
    """, user_id)

    current = int(wallet["credits"])
    updated = current + amount

    if updated > MAX_CREDITS:
        raise ValueError("Credit balance would exceed the allowed maximum.")

    if reference_id is not None:
        existing = await conn.fetchval("""
            SELECT 1
            FROM onyx_credit_transactions
            WHERE user_id=$1
              AND source=$2
              AND reference_id=$3
        """, user_id, source, reference_id)

        if existing:
            return {
                "ok": False,
                "duplicate": True,
                "credits": current
            }

    await conn.execute("""
        UPDATE onyx_credit_wallet
        SET credits=$1,
            lifetime_earned=lifetime_earned+$2,
            updated_at=CURRENT_TIMESTAMP
        WHERE user_id=$3
    """, updated, amount, user_id)

    await conn.execute("""
        INSERT INTO onyx_credit_transactions (
            user_id,
            amount,
            balance_after,
            transaction_type,
            source,
            reference_id,
            description
        )
        VALUES($1, $2, $3, 'earn', $4, $5, $6)
    """,
        user_id,
        amount,
        updated,
        source,
        reference_id,
        str(description)[:240]
    )

    return {
        "ok": True,
        "duplicate": False,
        "credits": updated
    }


async def spend_credits(
    conn,
    user_id,
    amount,
    source,
    description=""
):
    """Spend Credits safely.

    Call this inside an existing database transaction.
    """

    amount = int(amount)

    if amount < 0 or amount > MAX_CREDITS:
        raise ValueError("Credit cost must be a valid non-negative amount.")

    if amount == 0:
        return {
            "ok": True,
            "credits": await get_credit_balance(conn, user_id)
        }

    await ensure_credit_wallet(conn, user_id)

    wallet = await conn.fetchrow("""
        SELECT credits
        FROM onyx_credit_wallet
        WHERE user_id=$1
        FOR UPDATE
    """, user_id)

    current = int(wallet["credits"])

    if current < amount:
        return {
            "ok": False,
            "error": "Not enough ONYX Credits.",
            "credits": current,
            "required": amount
        }

    updated = current - amount

    await conn.execute("""
        UPDATE onyx_credit_wallet
        SET credits=$1,
            lifetime_spent=lifetime_spent+$2,
            updated_at=CURRENT_TIMESTAMP
        WHERE user_id=$3
    """, updated, amount, user_id)

    await conn.execute("""
        INSERT INTO onyx_credit_transactions (
            user_id,
            amount,
            balance_after,
            transaction_type,
            source,
            description
        )
        VALUES($1, $2, $3, 'spend', $4, $5)
    """,
        user_id,
        -amount,
        updated,
        str(source)[:48],
        str(description)[:240]
    )

    return {
        "ok": True,
        "credits": updated
    }
