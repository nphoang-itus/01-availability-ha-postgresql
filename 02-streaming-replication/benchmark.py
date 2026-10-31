import argparse
import asyncio
import json
import math
import os
import time
import uuid
from collections import Counter
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

import psycopg


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def percentile(values, percent):
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * percent / 100) - 1)
    return round(ordered[index], 3)


async def main(args):
    run_id = str(uuid.uuid4())
    output_dir = Path("results") / run_id
    output_dir.mkdir(parents=True)

    queue = asyncio.Queue(maxsize=100)
    counts = Counter()
    success_latencies = []
    start_delays = []

    total = args.rate * args.duration
    started_at = utc_now()
    started = time.monotonic()

    print(f"run_id: {run_id}", flush=True)
    print(f"output: {output_dir}", flush=True)
    print(
        f"target: {args.rate} req/s, "
        f"duration: {args.duration}s, workers: {args.workers}",
        flush=True,
    )

    with (output_dir / "requests.jsonl").open("w") as log:

        def record(item):
            counts[item["status"]] += 1
            log.write(json.dumps(item, ensure_ascii=False) + "\n")
            log.flush()

        async def worker():
            conn = None
            connection_port = None
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        queue.task_done()
                        break

                    request_started = time.monotonic()
                    item["started_at"] = utc_now()
                    item["start_delay_ms"] = round(
                        (request_started - started
                         - item["scheduled_offset_s"]) * 1000, 3
                    )
                    start_delays.append(item["start_delay_ms"])
                    phase = "connect"

                    try:
                        target_port = (
                            int(Path(args.port_file).read_text().strip())
                            if args.port_file
                            else int(os.getenv("PGPORT", "5432"))
                        )
                        item["target_port"] = target_port

                        if conn is not None and connection_port != target_port:
                            await asyncio.wait_for(conn.close(), timeout=1)
                            conn = None

                        if conn is None or conn.closed:
                            conn = await asyncio.wait_for(
                                psycopg.AsyncConnection.connect(
                                    port=target_port,
                                    connect_timeout=3,
                                    application_name="ha-lab-benchmark",
                                    options="-c statement_timeout=2000",
                                ),
                                timeout=4,
                            )
                            connection_port = target_port

                        phase = "insert"
                        cursor = await asyncio.wait_for(
                            conn.execute(
                                """
                                INSERT INTO public.write_events
                                    (request_id, run_id, sequence_no, payload)
                                VALUES (%s, %s, %s, %s)
                                """,
                                (
                                    uuid.UUID(item["request_id"]),
                                    uuid.UUID(run_id),
                                    item["sequence_no"],
                                    "x" * 100,
                                ),
                            ),
                            timeout=3,
                        )
                        await cursor.close()

                        phase = "commit"
                        await asyncio.wait_for(conn.commit(), timeout=3)
                        item["status"] = "success"

                    except Exception as exc:
                        item["status"] = (
                            "unknown" if phase == "commit" else "failed"
                        )
                        item["error_type"] = type(exc).__name__
                        item["sqlstate"] = getattr(exc, "sqlstate", None)
                        item["error"] = str(exc)[:500]

                        if conn is not None:
                            with suppress(Exception):
                                await asyncio.wait_for(conn.close(), timeout=1)
                        conn = None

                    item["phase"] = phase
                    item["finished_at"] = utc_now()
                    item["finished_offset_s"] = round(
                        time.monotonic() - started, 6
                    )
                    item["latency_ms"] = round(
                        (time.monotonic() - request_started) * 1000, 3
                    )

                    if item["status"] == "success":
                        success_latencies.append(item["latency_ms"])

                    record(item)
                    queue.task_done()

            finally:
                if conn is not None:
                    with suppress(Exception):
                        await conn.close()

        workers = [
            asyncio.create_task(worker())
            for _ in range(args.workers)
        ]

        for sequence_no in range(total):
            scheduled_offset = sequence_no / args.rate
            await asyncio.sleep(
                max(0, started + scheduled_offset - time.monotonic())
            )

            item = {
                "run_id": run_id,
                "request_id": str(uuid.uuid4()),
                "sequence_no": sequence_no,
                "scheduled_offset_s": scheduled_offset,
            }

            # Skip overdue requests to avoid a large catch-up burst.
            if time.monotonic() - started - scheduled_offset > 0.1:
                item.update(
                    status="not_sent",
                    reason="scheduler_late",
                    recorded_at=utc_now(),
                )
                record(item)
            else:
                try:
                    queue.put_nowait(item)
                except asyncio.QueueFull:
                    item.update(
                        status="not_sent",
                        reason="queue_full",
                        recorded_at=utc_now(),
                    )
                    record(item)

            if sequence_no and sequence_no % (args.rate * 10) == 0:
                print(
                    f"scheduled={sequence_no + 1}/{total} "
                    f"results={dict(counts)} queue={queue.qsize()}",
                    flush=True,
                )

        await asyncio.sleep(
            max(0, started + args.duration - time.monotonic())
        )
        await queue.join()

        for _ in workers:
            await queue.put(None)
        await asyncio.gather(*workers)

    elapsed = time.monotonic() - started
    attempted = sum(counts[s] for s in ("success", "failed", "unknown"))
    client_errors = counts["failed"] + counts["unknown"]

    summary = {
        "run_id": run_id,
        "label": args.label,
        "started_at": started_at,
        "started_monotonic_s": started,
        "finished_at": utc_now(),
        "target_rate": args.rate,
        "duration_s": args.duration,
        "workers": args.workers,
        "port_file": args.port_file,
        "target": {
            key: os.getenv(key)
            for key in ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER")
        },
        "scheduled": total,
        "attempted": attempted,
        "success": counts["success"],
        "failed": counts["failed"],
        "unknown": counts["unknown"],
        "not_sent": counts["not_sent"],
        "client_error_rate_pct": round(
            100 * client_errors / attempted, 3
        ) if attempted else None,
        "elapsed_including_drain_s": round(elapsed, 3),
        "success_per_s_including_drain": round(
            counts["success"] / elapsed, 3
        ),
        "success_latency_ms": {
            "p50": percentile(success_latencies, 50),
            "p95": percentile(success_latencies, 95),
            "p99": percentile(success_latencies, 99),
        },
        "start_delay_p95_ms": percentile(start_delays, 95),
    }

    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False)
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rate", type=int, default=50)
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--label", default="baseline")
    parser.add_argument(
        "--port-file",
        default=None,
        help="Read the destination port from this file before each request",
    )
    args = parser.parse_args()

    if min(args.rate, args.duration, args.workers) <= 0:
        parser.error("rate, duration and workers must be positive")

    asyncio.run(main(args))
