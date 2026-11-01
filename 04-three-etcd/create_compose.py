from copy import deepcopy
from pathlib import Path

import yaml

output = Path("compose.yaml")
if output.exists():
    raise SystemExit("compose.yaml already exists. Inspect it before regenerating.")

base = yaml.safe_load(Path("compose.single-etcd.yaml").read_text())
overlay = yaml.safe_load(Path("compose.haproxy.yaml").read_text())

base["name"] = "ha-lab-three-etcd"

template = base["services"].pop("etcd")
base["volumes"].pop("etcd_data", None)

names = ["etcd-01", "etcd-02", "etcd-03"]
initial_cluster = ",".join(
    f"{name}=http://{name}:2380" for name in names
)

for name in names:
    service = deepcopy(template)
    volume = name.replace("-", "_") + "_data"

    service["command"] = [
        "/usr/local/bin/etcd",
        f"--name={name}",
        "--data-dir=/etcd-data",
        "--listen-client-urls=http://0.0.0.0:2379",
        f"--advertise-client-urls=http://{name}:2379",
        "--listen-peer-urls=http://0.0.0.0:2380",
        f"--initial-advertise-peer-urls=http://{name}:2380",
        f"--initial-cluster={initial_cluster}",
        "--initial-cluster-state=new",
        "--initial-cluster-token=ha-lab-three-etcd",
        "--enable-grpc-gateway=true",
    ]
    service["volumes"] = [f"{volume}:/etcd-data"]

    base["services"][name] = service
    base["volumes"][volume] = {}

for node in ("pg-01", "pg-02"):
    base["services"][node]["depends_on"] = {
        name: {"condition": "service_healthy"}
        for name in names
    }

base["services"].update(overlay["services"])

output.write_text(yaml.safe_dump(base, sort_keys=False))
print("Created compose.yaml with three etcd members and HAProxy.")
