import asyncio
import statistics
import time

import discord
from discord.ext import commands


class StressTest(commands.Cog):
    """Bounded, owner-only internal performance benchmark."""

    def __init__(self, bot):
        self.bot = bot
        self._test_lock = asyncio.Lock()

    @commands.command(
        name="stresstest",
        hidden=True,
        help="Run a bounded internal performance benchmark. Owner only."
    )
    @commands.is_owner()
    async def stresstest(
        self,
        ctx: commands.Context,
        seconds: int = 5,
        workers: int = 4
    ):
        # Hard limits protect the shared bot/database process.
        if not 1 <= seconds <= 20:
            return await ctx.send("Duration must be between 1 and 20 seconds.")
        if not 1 <= workers <= 8:
            return await ctx.send("Workers must be between 1 and 8.")

        if self._test_lock.locked():
            return await ctx.send("A stress test is already running. Please wait for it to finish.")

        async with self._test_lock:
            started = time.perf_counter()
            deadline = started + seconds
            max_operations = 1000

            completed = 0
            errors = 0
            latencies = []
            counter_lock = asyncio.Lock()
            stop_heartbeat = asyncio.Event()
            heartbeat_delays = []

            async def heartbeat():
                interval = 0.05
                expected = time.perf_counter() + interval
                while not stop_heartbeat.is_set():
                    try:
                        await asyncio.wait_for(stop_heartbeat.wait(), timeout=interval)
                    except asyncio.TimeoutError:
                        now = time.perf_counter()
                        heartbeat_delays.append(max(0.0, now - expected))
                        expected = now + interval

            async def worker():
                nonlocal completed, errors
                while time.perf_counter() < deadline:
                    async with counter_lock:
                        if completed + errors >= max_operations:
                            return

                    request_started = time.perf_counter()
                    try:
                        # Read-only query: does not create tables or modify user data.
                        await asyncio.wait_for(
                            self.bot.db.fetchone("SELECT 1", ()),
                            timeout=5.0
                        )
                        elapsed_ms = (time.perf_counter() - request_started) * 1000
                        async with counter_lock:
                            completed += 1
                            latencies.append(elapsed_ms)
                    except Exception:
                        async with counter_lock:
                            errors += 1

            heartbeat_task = asyncio.create_task(heartbeat())
            tasks = [
                asyncio.create_task(worker())
                for _ in range(workers)
            ]

            try:
                await asyncio.gather(*tasks)
            finally:
                stop_heartbeat.set()
                await heartbeat_task

            total_seconds = max(0.001, time.perf_counter() - started)
            total = completed + errors
            rate = completed / total_seconds

            if latencies:
                average_ms = statistics.fmean(latencies)
                sorted_latencies = sorted(latencies)
                p95_index = min(
                    len(sorted_latencies) - 1,
                    int(0.95 * len(sorted_latencies))
                )
                p95_ms = sorted_latencies[p95_index]
                max_ms = max(sorted_latencies)
            else:
                average_ms = p95_ms = max_ms = 0.0

            max_loop_delay = max(heartbeat_delays, default=0.0) * 1000

            embed = discord.Embed(
                title="ONYX • Stress Test Results",
                description=(
                    "Completed a bounded, read-only database benchmark. "
                    "No test messages were sent to other channels."
                ),
                color=discord.Color.from_rgb(44, 38, 67),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(
                name="Test configuration",
                value=(
                    f"Duration: **{total_seconds:.2f}s**\n"
                    f"Workers: **{workers}**\n"
                    f"Operation cap: **{max_operations}**"
                ),
                inline=True
            )
            embed.add_field(
                name="Database workload",
                value=(
                    f"Successful checks: **{completed:,}**\n"
                    f"Errors/timeouts: **{errors:,}**\n"
                    f"Throughput: **{rate:.1f} checks/sec**"
                ),
                inline=True
            )
            embed.add_field(
                name="Response times",
                value=(
                    f"Average: **{average_ms:.2f} ms**\n"
                    f"95th percentile: **{p95_ms:.2f} ms**\n"
                    f"Maximum: **{max_ms:.2f} ms**"
                ),
                inline=True
            )
            embed.add_field(
                name="Event-loop responsiveness",
                value=f"Maximum observed heartbeat delay: **{max_loop_delay:.2f} ms**",
                inline=False
            )
            embed.add_field(
                name="What this test measures",
                value=(
                    "Read-only `SELECT 1` database checks and event-loop scheduling. "
                    "It does **not** measure Discord message throughput, gateway capacity, "
                    "or real user traffic."
                ),
                inline=False
            )
            embed.set_footer(
                text="ONYX • Owner-only benchmark • Maximum 20 seconds / 8 workers"
            )
            await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(StressTest(bot))
