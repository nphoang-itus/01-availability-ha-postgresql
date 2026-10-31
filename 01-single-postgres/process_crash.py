import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def mark():
    return {
        "utc": datetime.now(timezone.utc).isoformat(),
        "monotonic_s": time.monotonic(),
    }


def inspect():
    return json.loads(subprocess.check_output(
        ["docker", "inspect", "ha-lab-single-postgres-1"],
        text=True,
    ))[0]


parser = argparse.ArgumentParser()
parser.add_argument("run_id")
parser.add_argument("--manual", action="store_true")
args = parser.parse_args()

folder = Path("results") / args.run_id
if not folder.is_dir():
    raise SystemExit("Không tìm thấy thư mục benchmark.")

output = folder / "process-crash.json"
if output.exists():
    raise SystemExit("Lần chạy này đã có kết quả gây lỗi.")

before = inspect()
events = {
    "method": "pg_ctl immediate",
    "manual_recovery": args.manual,
    "restart_count_before": before["RestartCount"],
    "restart_policy": before["HostConfig"]["RestartPolicy"]["Name"],
}


def save():
    output.write_text(json.dumps(events, indent=2))


events["crash_before"] = mark()
save()

with (folder / "process-crash.log").open("w") as log:
    result = subprocess.run(
        [
            "docker", "exec", "--user", "postgres",
            "ha-lab-single-postgres-1",
            "sh", "-c",
            'pg_ctl -D "$PGDATA" stop -m immediate -W',
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
    )

events["crash_after"] = mark()
events["command_returncode"] = result.returncode
save()

# Xác nhận container đã thoát hoặc đã được restart.
observed = False
for _ in range(75):
    current = inspect()
    if (
        current["RestartCount"] > before["RestartCount"]
        or not current["State"]["Running"]
        or current["State"]["StartedAt"] != before["State"]["StartedAt"]
    ):
        observed = True
        break
    time.sleep(0.2)

events["crash_observed"] = observed
events["state_observed"] = current["State"]
save()

if not observed:
    raise SystemExit("Chưa xác nhận được crash; xem process-crash.log.")

if args.manual:
    input("Quan sát lỗi khoảng 20 giây, rồi nhấn Enter để phục hồi...")
    events["restart_before"] = mark()
    save()
    subprocess.run(
        ["docker", "start", "ha-lab-single-postgres-1"],
        check=True,
    )
    events["restart_after"] = mark()
else:
    print("Để Docker tự phục hồi; không chạy docker start.")

events["inspection_at_end"] = inspect()
save()
print("Đã lưu:", output)
