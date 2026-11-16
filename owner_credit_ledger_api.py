
"""ONYX owner-only bot credit earnings ledger."""

from aiohttp import web


BOT_REWARD_PREFIX = "reward_"


def register_credit_ledger_routes(app, require_user, bot_owner_id):

    async def require_owner(request):
        user_id = require_user(request)

        if not bot_owner_id or str(user_id) != str(bot_owner_id):
            raise web.HTTPForbidden(
                text='{"error":"Only the ONYX owner can access this ledger."}',
                content_type="application/json"
            )

        return int(user_id)

    async def summary(request):
        await require_owner(request)

        async with request.app["db"].acquire() as conn:
            row = await conn.fetchrow("""
                SELECT
                    COUNT(*) AS transaction_count,
                    COUNT(DISTINCT user_id) AS users_rewarded,
                    COALESCE(SUM(amount), 0) AS total_earned
                FROM onyx_credit_transactions
                WHERE transaction_type = 'earn'
                  AND LEFT(source, 7) = 'reward_'
                  AND amount > 0
            """)

            by_source = await conn.fetch("""
                SELECT
                    source,
                    COUNT(*) AS transaction_count,
                    COALESCE(SUM(amount), 0) AS total_earned
                FROM onyx_credit_transactions
                WHERE transaction_type = 'earn'
                  AND LEFT(source, 7) = 'reward_'
                  AND amount > 0
                GROUP BY source
                ORDER BY total_earned DESC
            """)

        return web.json_response({
            "total_earned": int(row["total_earned"]),
            "transaction_count": int(row["transaction_count"]),
            "users_rewarded": int(row["users_rewarded"]),
            "sources": [
                {
                    "source": item["source"],
                    "transaction_count": int(item["transaction_count"]),
                    "total_earned": int(item["total_earned"])
                }
                for item in by_source
            ]
        })

    async def transactions(request):
        await require_owner(request)

        try:
            limit = int(request.query.get("limit", "50"))
            limit = max(1, min(limit, 100))

            before = request.query.get("before")
            before = int(before) if before else None

            user_id = request.query.get("user_id", "").strip()
            source = request.query.get("source", "").strip().lower()
            search = request.query.get("search", "").strip()

            if user_id and not user_id.isdigit():
                raise ValueError()

            if source and source not in {
                "reward_daily",
                "reward_weekly",
                "reward_work",
                "reward_beg"
            }:
                raise ValueError()

            if before is not None and before < 1:
                raise ValueError()

        except (TypeError, ValueError):
            return web.json_response(
                {"error": "Invalid ledger filters."},
                status=400
            )

        conditions = [
            "t.transaction_type = 'earn'",
            "LEFT(t.source, 7) = 'reward_'",
            "t.amount > 0"
        ]
        values = []

        def add_condition(sql, value):
            values.append(value)
            conditions.append(sql.replace("?", f"${len(values)}"))

        if before is not None:
            add_condition("t.id < ?", before)

        if user_id:
            add_condition("t.user_id = ?", int(user_id))

        if source:
            add_condition("t.source = ?", source)

        if search:
            add_condition(
                "(CAST(t.user_id AS TEXT) = ? OR "
                "LOWER(COALESCE(p.display_name, '')) LIKE ?)",
                search
            )
            values.append("%" + search.lower() + "%")
            conditions[-1] = (
                conditions[-1].replace(
                    f"${len(values)-1}",
                    f"${len(values)-1}"
                )
            )

        where_clause = " AND ".join(conditions)

        query = f"""
            SELECT
                t.id,
                t.user_id,
                t.amount,
                t.balance_after,
                t.source,
                t.description,
                t.created_at,
                p.display_name
            FROM onyx_credit_transactions t
            LEFT JOIN onyx_discord_user_profiles p
                ON p.user_id = t.user_id
            WHERE {where_clause}
            ORDER BY t.id DESC
            LIMIT ${len(values) + 1}
        """

        values.append(limit + 1)

        async with request.app["db"].acquire() as conn:
            rows = await conn.fetch(query, *values)

        has_more = len(rows) > limit
        rows = rows[:limit]

        items = []

        for row in rows:
            items.append({
                "id": int(row["id"]),
                "user_id": str(row["user_id"]),
                "display_name": row["display_name"] or None,
                "amount": int(row["amount"]),
                "balance_after": int(row["balance_after"]),
                "source": row["source"],
                "description": row["description"] or "",
                "created_at": (
                    row["created_at"].isoformat()
                    if row["created_at"] else None
                )
            })

        return web.json_response({
            "transactions": items,
            "has_more": has_more,
            "next_before": (
                items[-1]["id"] if has_more and items else None
            )
        })

    app.router.add_get(
        "/api/owner/credits/summary",
        summary
    )
    app.router.add_get(
        "/api/owner/credits/transactions",
        transactions
    )
