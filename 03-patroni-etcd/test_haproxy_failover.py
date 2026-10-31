import argparse
import json
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
            f"http://127.0.0.1:{port}/primary", timeout=1
        ) as response:
            return response.status
    except HTTPError as exc:
        return exc.code
    except (URLError, TimeoutError, OSError):
        return None


parser = argparse.ArgumentParser()
parser.add_argument("run_id")
args = parser.parse_args()

folder = Path("results") / args.run_id
output = folder / "haproxy-failover.json"

if not folder.is_dir() or output.exists():
    raise SystemExit("Missing run directory or existing failover result.")

api_ports = {"pg-01": 18008, "pg-02": 18009}
statuses = {
    name: primary_status(port)
    for name, port in api_ports.items()
}
leaders = [name for name, status in statuses.items() if status == 200]

if len(leaders) != 1:
    raise SystemExit(f"Expected exactly one primary: {statuses}")

old_leader = leaders[0]
new_leader = next(name for name in api_ports if name != old_leader)

if statuses[new_leader] != 503:
    raise SystemExit("The other node must be available as a non-primary.")

container_id = subprocess.check_output(
    ["docker", "compose", "ps", "-q", old_leader],
    text=True,
).strip()
container = json.loads(subprocess.check_output(
    ["docker", "inspect", container_id], text=True
))[0]

if container["HostConfig"]["RestartPolicy"]["Name"] != "no":
    raise SystemExit("The target must have restart policy 'no'.")

events = {
    "old_leader": old_leader,
    "new_leader": new_leader,
    "client_port": 5000,
    "probes": [],
}


def save():
    output.write_text(json.dumps(events, indent=2))


print(f"Killing current leader: {old_leader}", flush=True)
events["kill_before"] = mark()
save()

with (folder / "pumba.log").open("w") as log:
    result = subprocess.run(
        [
            "docker", "run", "--rm",
            "-v", "/var/run/docker.sock:/var/run/docker.sock",
            "ghcr.io/alexei-led/pumba:latest",
            "--log-level", "info",
            "kill", "--signal", "SIGKILL",
            container["Name"].lstrip("/"),
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
        timeout=30,
    )

events["kill_after"] = mark()
events["pumba_returncode"] = result.returncode
save()
result.check_returncode()

deadline = time.monotonic() + 90
while time.monotonic() < deadline:
    probe = {"before": mark()}
    probe["status"] = primary_status(api_ports[new_leader])
    probe["after"] = mark()
    events["probes"].append(probe)
    save()

    if probe["status"] == 200:
        events["new_primary_detected"] = probe["after"]
        save()
        print(f"New primary detected: {new_leader}")
        print("Keep the client on port 5000 and let the benchmark finish.")
        break

    time.sleep(0.5)
else:
    raise SystemExit("No new primary detected within 90 seconds.")
