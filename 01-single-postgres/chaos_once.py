import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def mark():
    return {
        "utc": datetime.now(timezone.utc).isoformat(),
        "monotonic_s": time.monotonic(),
    }


if len(sys.argv) != 2:
    raise SystemExit("Usage: python chaos_once.py <benchmark-run-id>")

run_dir = Path("results") / sys.argv[1]
if not run_dir.is_dir():
    raise SystemExit("Không tìm thấy thư mục của benchmark đang chạy.")

output = run_dir / "chaos.json"
if output.exists():
    raise SystemExit("Lần chạy này đã có chaos.json; dùng một benchmark mới.")

target = "ha-lab-single-postgres-1"
image = "ghcr.io/alexei-led/pumba:latest"

events = {
    "target": target,
    "pumba_image": image,
}


def save():
    output.write_text(json.dumps(events, indent=2))


events["kill_before"] = mark()
save()

with (run_dir / "pumba.log").open("w") as log:
    result = subprocess.run(
        [
            "docker", "run", "--rm",
            "-v", "/var/run/docker.sock:/var/run/docker.sock",
            image,
            "--log-level", "info",
            "kill", "--signal", "SIGKILL", target,
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
    )

events["kill_after"] = mark()
events["pumba_returncode"] = result.returncode
save()
result.check_returncode()

state = json.loads(subprocess.check_output(
    ["docker", "inspect", target, "--format", "{{json .State}}"],
    text=True,
))
events["state_after_kill"] = state
save()

print("Container status:", state["Status"])
print("Exit code:", state["ExitCode"])
print("Đã lưu:", output)

if state["Running"]:
    raise SystemExit("Container vẫn chạy; dừng và kiểm tra lại thí nghiệm.")

input(
    "\nQuan sát lỗi trong khoảng 20 giây. "
    "Nhấn Enter khi bạn muốn khởi động lại PostgreSQL..."
)

events["restart_before"] = mark()
save()

result = subprocess.run(["docker", "start", target])

events["restart_after"] = mark()
events["restart_returncode"] = result.returncode
save()
result.check_returncode()

print("Đã gửi lệnh khởi động. Để benchmark tiếp tục chạy đến hết.")
