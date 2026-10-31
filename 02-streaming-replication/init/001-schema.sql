CREATE ROLE benchmark
    LOGIN
    PASSWORD 'lab_benchmark_password';

CREATE TABLE public.write_events (
    request_id UUID PRIMARY KEY,
    run_id UUID NOT NULL,
    sequence_no BIGINT NOT NULL,
    payload TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

GRANT CONNECT ON DATABASE ha_lab TO benchmark;
GRANT USAGE ON SCHEMA public TO benchmark;
GRANT SELECT, INSERT ON TABLE public.write_events TO benchmark;
