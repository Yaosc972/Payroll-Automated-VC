create extension if not exists pgcrypto;

create table if not exists labor_runs (
    id text primary key,
    organization_id text,
    created_by text,
    supplier_name text not null,
    period_start date not null,
    period_end date not null,
    currency text not null,
    status text not null default 'draft',
    stage text,
    progress smallint not null default 0 check (progress between 0 and 100),
    input_manifest_hash text,
    engine_version text,
    rules_version text,
    model_version text,
    error_code text,
    error_message text,
    retryable boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    started_at timestamptz,
    finished_at timestamptz
);

create table if not exists labor_files (
    id uuid primary key default gen_random_uuid(),
    run_id text not null,
    file_role text not null,
    bucket text not null,
    object_path text not null,
    original_filename text not null,
    mime_type text,
    size_bytes bigint,
    sha256 text,
    status text not null default 'pending',
    uploaded_at timestamptz,
    verified_at timestamptz,
    created_at timestamptz not null default now(),
    unique (bucket, object_path)
);

create table if not exists labor_jobs (
    id text primary key,
    run_id text not null,
    job_type text not null default 'reconcile',
    status text not null default 'queued',
    priority integer not null default 100,
    attempt integer not null default 0,
    max_attempts integer not null default 5,
    available_at timestamptz not null default now(),
    worker_id text,
    lease_expires_at timestamptz,
    heartbeat_at timestamptz,
    error_code text,
    error_detail text,
    retryable boolean not null default false,
    metadata_snapshot jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    started_at timestamptz,
    finished_at timestamptz,
    updated_at timestamptz not null default now()
);

create unique index if not exists labor_one_active_job_per_run
on labor_jobs(run_id)
where status in ('queued', 'running', 'retry_wait');

create index if not exists labor_jobs_claim_idx
on labor_jobs(status, available_at, priority desc, created_at);

create index if not exists labor_jobs_running_lease_idx
on labor_jobs(status, lease_expires_at)
where status = 'running';

create table if not exists labor_job_attempts (
    id uuid primary key default gen_random_uuid(),
    job_id text not null references labor_jobs(id) on delete cascade,
    attempt_no integer not null,
    worker_id text,
    started_at timestamptz not null default now(),
    finished_at timestamptz,
    outcome text,
    error_code text,
    error_detail text,
    retryable boolean,
    unique(job_id, attempt_no)
);
