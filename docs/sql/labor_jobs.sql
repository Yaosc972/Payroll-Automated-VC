-- Overseas labor personal Worker queue.
-- Apply manually to the dedicated UAT Postgres database before enabling
-- SIGMA_LABOR_JOB_BACKEND=postgres. This script does not grant application users
-- direct table access; the server uses its private database connection.

create table if not exists public.labor_jobs (
    id text primary key,
    run_id text not null,
    job_type text not null default 'reconcile',
    status text not null default 'queued',
    priority integer not null default 100,
    attempt integer not null default 0,
    max_attempts integer not null default 3,
    available_at timestamptz not null default now(),
    retryable boolean not null default false,
    metadata_snapshot jsonb not null default '{}'::jsonb,
    worker_id text,
    lease_expires_at timestamptz,
    heartbeat_at timestamptz,
    error_code text,
    error_detail text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    started_at timestamptz,
    finished_at timestamptz,
    constraint labor_jobs_status_check check (
        status in ('queued', 'running', 'retry_wait', 'succeeded', 'failed')
    ),
    constraint labor_jobs_attempt_check check (
        attempt >= 0 and max_attempts >= 1 and attempt <= max_attempts
    )
);

create unique index if not exists labor_jobs_one_active_run_idx
    on public.labor_jobs (run_id)
    where status in ('queued', 'running', 'retry_wait');

create index if not exists labor_jobs_claim_idx
    on public.labor_jobs (priority desc, available_at, created_at)
    where status in ('queued', 'running', 'retry_wait');

create index if not exists labor_jobs_owner_idx
    on public.labor_jobs ((metadata_snapshot ->> 'ownerUserId'), updated_at desc);

comment on table public.labor_jobs is
    'Durable queue for overseas-labor reconciliation jobs claimed by registered desktop Workers.';
