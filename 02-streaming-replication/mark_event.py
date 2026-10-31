import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if len(sys.argv) != 3:
    raise SystemExit("Usage: python mark_event.py <run-id> <event-name>")

run_id, event_name = sys.argv[1:]
folder = Path("results") / run_id

if not folder.is_dir():
    raise SystemExit("Benchmark output directory does not exist.")

path = folder / "failover-events.json"
events = json.loads(path.read_text()) if path.exists() else {}

if event_name in events:
    raise SystemExit(f"Event already exists: {event_name}")

events[event_name] = {
    "utc": datetime.now(timezone.utc).isoformat(),
    "monotonic_s": time.monotonic(),
}
path.write_text(json.dumps(events, indent=2))
print(f"Recorded event: {event_name}")
