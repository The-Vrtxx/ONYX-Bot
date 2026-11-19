"""Call after ArcadeManager.record_stats successfully stores a settled round."""
from cogs.achievements.engine import add_metric,get_metric,set_metric,evaluate

async def record_arcade_result(bot,user_id,game,wager,outcome,payout,reference=None):
    db=bot.db; uid=int(user_id); game=str(game).casefold(); outcome=str(outcome).casefold()
    wager=int(wager or 0); payout=int(payout or 0)
    await add_metric(db,uid,"arcade_games")
    await add_metric(db,uid,"arcade_wagered",wager)
    await add_metric(db,uid,"arcade_total_payout",payout)
    await set_metric(db,uid,"arcade_biggest_return",max(await get_metric(db,uid,"arcade_biggest_return"),payout))
    await db.execute("INSERT INTO onyx_achievement_arcade_games(user_id,game,won) VALUES(?,?,?) ON CONFLICT(user_id,game) DO UPDATE SET won=MAX(onyx_achievement_arcade_games.won,excluded.won)",(uid,game,1 if outcome=="win" else 0))
    row=await db.fetchone("SELECT COUNT(*) AS n FROM onyx_achievement_arcade_games WHERE user_id=?",(uid,)); await set_metric(db,uid,"arcade_unique_games",row["n"])
    row=await db.fetchone("SELECT COUNT(*) AS n FROM onyx_achievement_arcade_games WHERE user_id=? AND won=1",(uid,)); await set_metric(db,uid,"arcade_unique_won_games",row["n"])
    if outcome=="win":
        await add_metric(db,uid,"arcade_wins")
        streak=await get_metric(db,uid,"arcade_current_win_streak")+1
        await set_metric(db,uid,"arcade_current_win_streak",streak)
        await set_metric(db,uid,"arcade_best_win_streak",max(streak,await get_metric(db,uid,"arcade_best_win_streak")))
        if await get_metric(db,uid,"arcade_current_loss_streak")>=5: await add_metric(db,uid,"arcade_comeback_wins")
        await set_metric(db,uid,"arcade_current_loss_streak",0)
    elif outcome=="loss":
        await add_metric(db,uid,"arcade_current_loss_streak")
        await set_metric(db,uid,"arcade_current_win_streak",0)
    if wager and payout>=wager*2:
        await set_metric(db,uid,"arcade_best_payout_multiplier_x100",max(await get_metric(db,uid,"arcade_best_payout_multiplier_x100"),int(payout*100/wager)))
    await evaluate(bot,uid)
