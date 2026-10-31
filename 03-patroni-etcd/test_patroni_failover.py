import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def mark():
    return {
        "utc": datetime.now(timezone.utc).isoformat(),
        "monotonic_s": time.monotonic(),
    }


def primary_status(port):
    try:
        with urlopen(
            f"http://127.0.0.1:{port}/primary",
            timeout=1,
        ) as response:
            return response.status
    except HTTPError as exc:
        return exc.code
    except (URLError, TimeoutError, OSError):
        return None


parser = argparse.ArgumentParser()
parser.add_argument("run_id")
parser.add_argument("--port-file", default="target-port.txt")
args = parser.parse_args()

folder = Path("results") / args.run_id
port_file = Path(args.port_file)
output = folder / "patroni-failover.json"

if not folder.is_dir():
    raise SystemExit("Benchmark output directory does not exist.")
if output.exists():
    raise SystemExit("This run already has a failover result.")
if port_file.read_text().strip() != "35432":
    raise SystemExit("The benchmark must initially target port 35432.")
if primary_status(18008) != 200 or primary_status(18009) != 503:
    raise SystemExit("Expected pg-01 as primary and pg-02 as replica.")

container_id = subprocess.check_output(
    ["docker", "compose", "ps", "-q", "pg-01"],
    text=True,
).strip()
container = json.loads(subprocess.check_output(
    ["docker", "inspect", container_id],
    text=True,
))[0]

if container["HostConfig"]["RestartPolicy"]["Name"] != "no":
    raise SystemExit("pg-01 must have restart policy 'no'.")

container_name = container["Name"].lstrip("/")
events = {
    "target": container_name,
    "old_port": 35432,
    "new_port": 35433,
    "probes": [],
}


def save():
    output.write_text(json.dumps(events, indent=2))


events["kill_before"] = mark()
save()

with (folder / "pumba.log").open("w") as log:
    result = subprocess.run(
        [
            "docker", "run", "--rm",
            "-v", "/var/run/docker.sock:/var/run/docker.sock",
            "ghcr.io/alexei-led/pumba:latest",
            "--log-level", "info",
            "kill", "--signal", "SIGKILL", container_name,
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
        timeout=30,
    )

events["kill_after"] = mark()
events["pumba_returncode"] = result.returncode
save()
result.check_returncode()

state = json.loads(subprocess.check_output(
    ["docker", "inspect", container_id, "--format", "{{json .State}}"],
    text=True,
))
events["old_node_state"] = state
save()

if state["Running"]:
    raise SystemExit("The old primary is still running.")

print("Old primary stopped. Waiting for automatic promotion...", flush=True)

deadline = time.monotonic() + 90

while time.monotonic() < deadline:
    probe = {"before": mark()}
    probe["status"] = primary_status(18009)
    probe["after"] = mark()
    events["probes"].append(probe)
    save()

    if probe["status"] == 200:
        events["new_primary_detected"] = probe["after"]
        save()
        print("pg-02 is now primary. HTTP /primary returned 200.", flush=True)
        break

    time.sleep(0.5)
else:
    raise SystemExit(
        "No new primary detected within 90 seconds. Inspect Patroni logs."
    )

input(
    "Observe that the benchmark still fails on port 35432. "
    "Press Enter to route new requests to port 35433..."
)

events["route_before"] = mark()
save()

temporary = port_file.with_name(port_file.name + ".tmp")
temporary.write_text("35433\n")
os.replace(temporary, port_file)

events["route_after"] = mark()
save()

print("Destination switched to port 35433.")
print("Let the benchmark finish.")
print(f"Results saved to: {output}")
