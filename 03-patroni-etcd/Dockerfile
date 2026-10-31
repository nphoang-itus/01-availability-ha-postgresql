FROM postgres:17-bookworm

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3-venv \
        curl \
        ca-certificates \
    && python3 -m venv /opt/patroni \
    && /opt/patroni/bin/pip install --no-cache-dir \
        "patroni[psycopg3,etcd3]==4.1.5" \
    && install -d -m 700 -o postgres -g postgres \
        /var/lib/postgresql/patroni \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/patroni/bin:${PATH}"

USER postgres

ENTRYPOINT ["patroni"]
CMD ["/etc/patroni/patroni.yaml"]
