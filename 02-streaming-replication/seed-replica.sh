#!/usr/bin/env bash
set -euo pipefail

if [ -f "$PGDATA/PG_VERSION" ]; then
    echo "Replica đã có dữ liệu; không sao chép đè."
    exit 1
fi

install -d -m 700 -o postgres -g postgres "$PGDATA"

exec gosu postgres pg_basebackup \
    --dbname="host=primary port=5432 user=replicator application_name=pg02" \
    --pgdata="$PGDATA" \
    --wal-method=stream \
    --write-recovery-conf \
    --slot=pg02 \
    --progress \
    --no-password
