-- Overseas labor P1 authoritative state schema.
--
-- Apply with the private server database role before setting
-- SIGMA_LABOR_STATE_BACKEND=postgres. Browser and Worker clients must never
-- receive this database credential. All timestamps are UTC timestamptz and all
-- mutable run transitions are serialized by locking labor_runs first.

begin;

create table if not exists public.labor_schema_versions (
    component text primary key,
    version integer not null,
    applied_at timestamptz not null default now(),
    constraint labor_schema_versions_version_positive check (version >= 1)
);

create table if not exists public.labor_runs (
    id text primary key,
    owner_user_id text not null,
    revision bigint not null default 1,
    status text not null default '已创建',
    supplier_name text not null default '',
    period_start date,
    period_end date,
    currency text not null default 'USD',
    idempotency_key text,
    metadata_snapshot jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    deleted_at timestamptz,
    constraint labor_runs_owner_not_blank check (btrim(owner_user_id) <> ''),
    constraint labor_runs_revision_positive check (revision >= 1),
    constraint labor_runs_currency_not_blank check (btrim(currency) <> '')
);

-- Upgrade the earlier P0 run table in place. CREATE TABLE IF NOT EXISTS does
-- not add P1 columns when a legacy table is already present, so add and
-- backfill them before creating owner-scoped indexes or foreign keys.
alter table public.labor_runs
    add column if not exists owner_user_id text;
alter table public.labor_runs
    add column if not exists revision bigint;
alter table public.labor_runs
    add column if not exists idempotency_key text;
alter table public.labor_runs
    add column if not exists metadata_snapshot jsonb;
alter table public.labor_runs
    add column if not exists deleted_at timestamptz;

do $$
declare
    has_created_by boolean;
    has_organization_id boolean;
begin
    select exists (
        select 1 from information_schema.columns
        where table_schema='public' and table_name='labor_runs' and column_name='created_by'
    ) into has_created_by;
    select exists (
        select 1 from information_schema.columns
        where table_schema='public' and table_name='labor_runs' and column_name='organization_id'
    ) into has_organization_id;

    if has_created_by and has_organization_id then
        execute $sql$
            update public.labor_runs
            set owner_user_id=coalesce(
                nullif(btrim(owner_user_id), ''),
                nullif(btrim(created_by), ''),
                nullif(btrim(organization_id), ''),
                'legacy:' || id
            )
            where owner_user_id is null or btrim(owner_user_id)=''
        $sql$;
    elsif has_created_by then
        execute $sql$
            update public.labor_runs
            set owner_user_id=coalesce(
                nullif(btrim(owner_user_id), ''),
                nullif(btrim(created_by), ''),
                'legacy:' || id
            )
            where owner_user_id is null or btrim(owner_user_id)=''
        $sql$;
    elsif has_organization_id then
        execute $sql$
            update public.labor_runs
            set owner_user_id=coalesce(
                nullif(btrim(owner_user_id), ''),
                nullif(btrim(organization_id), ''),
                'legacy:' || id
            )
            where owner_user_id is null or btrim(owner_user_id)=''
        $sql$;
    else
        update public.labor_runs
        set owner_user_id='legacy:' || id
        where owner_user_id is null or btrim(owner_user_id)='';
    end if;
end $$;

update public.labor_runs
set revision=coalesce(revision, 1),
    metadata_snapshot=coalesce(
        metadata_snapshot,
        jsonb_strip_nulls(jsonb_build_object(
            'id', id,
            'ownerUserId', owner_user_id,
            'status', status,
            'supplierName', supplier_name,
            'periodStart', period_start,
            'periodEnd', period_end,
            'currency', currency,
            'createdAt', created_at,
            'updatedAt', updated_at
        ))
    );

alter table public.labor_runs
    alter column owner_user_id set not null,
    alter column revision set default 1,
    alter column revision set not null,
    alter column metadata_snapshot set default '{}'::jsonb,
    alter column metadata_snapshot set not null;

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conrelid='public.labor_runs'::regclass and conname='labor_runs_owner_not_blank'
    ) then
        alter table public.labor_runs
            add constraint labor_runs_owner_not_blank
            check (btrim(owner_user_id) <> '') not valid;
    end if;
    if not exists (
        select 1 from pg_constraint
        where conrelid='public.labor_runs'::regclass and conname='labor_runs_revision_positive'
    ) then
        alter table public.labor_runs
            add constraint labor_runs_revision_positive
            check (revision >= 1) not valid;
    end if;
    if not exists (
        select 1 from pg_constraint
        where conrelid='public.labor_runs'::regclass and conname='labor_runs_currency_not_blank'
    ) then
        alter table public.labor_runs
            add constraint labor_runs_currency_not_blank
            check (btrim(currency) <> '') not valid;
    end if;
end $$;

alter table public.labor_runs validate constraint labor_runs_owner_not_blank;
alter table public.labor_runs validate constraint labor_runs_revision_positive;
alter table public.labor_runs validate constraint labor_runs_currency_not_blank;

create unique index if not exists labor_runs_owner_idempotency_idx
    on public.labor_runs (owner_user_id, idempotency_key)
    where idempotency_key is not null;
create index if not exists labor_runs_owner_updated_idx
    on public.labor_runs (owner_user_id, updated_at desc)
    where deleted_at is null;

create table if not exists public.labor_run_files (
    id text primary key,
    run_id text not null,
    owner_user_id text not null,
    file_kind text not null,
    object_key text not null,
    original_filename text not null default '',
    content_type text not null default 'application/octet-stream',
    size_bytes bigint not null default 0,
    sha256 text not null default '',
    upload_state text not null default 'ready',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    deleted_at timestamptz,
    foreign key (run_id) references public.labor_runs(id) on delete cascade,
    constraint labor_run_files_owner_not_blank check (btrim(owner_user_id) <> ''),
    constraint labor_run_files_size_nonnegative check (size_bytes >= 0),
    constraint labor_run_files_sha256_format check (sha256 = '' or sha256 ~ '^[0-9a-f]{64}$'),
    constraint labor_run_files_state_check check (upload_state in ('pending', 'ready', 'rejected', 'deleted')),
    unique (run_id, object_key)
);

create index if not exists labor_run_files_run_idx
    on public.labor_run_files (run_id, updated_at desc)
    where deleted_at is null;
create index if not exists labor_run_files_owner_idx
    on public.labor_run_files (owner_user_id, updated_at desc)
    where deleted_at is null;

create table if not exists public.labor_workbook_mappings (
    id bigint generated always as identity primary key,
    run_id text not null,
    owner_user_id text not null,
    version bigint not null,
    sheet_name text not null,
    mapping jsonb not null,
    manual_name_mapping jsonb not null default '{}'::jsonb,
    input_fingerprint text not null default '',
    actor_user_id text not null,
    created_at timestamptz not null default now(),
    foreign key (run_id) references public.labor_runs(id) on delete cascade,
    constraint labor_workbook_mappings_version_positive check (version >= 1),
    unique (run_id, version)
);

create index if not exists labor_workbook_mappings_run_idx
    on public.labor_workbook_mappings (run_id, version desc);

create table if not exists public.labor_business_reviews (
    id bigint generated always as identity primary key,
    run_id text not null,
    owner_user_id text not null,
    reviewer_user_id text not null,
    decision text not null,
    reason text not null default '',
    result_input_fingerprint text not null default '',
    run_revision bigint not null,
    created_at timestamptz not null default now(),
    foreign key (run_id) references public.labor_runs(id) on delete cascade,
    constraint labor_business_reviews_decision_check check (decision in ('pending', 'approved', 'rejected')),
    constraint labor_business_reviews_revision_positive check (run_revision >= 1)
);

create index if not exists labor_business_reviews_run_idx
    on public.labor_business_reviews (run_id, created_at desc);

create table if not exists public.labor_worker_devices (
    id text primary key,
    owner_user_id text not null,
    display_name text not null,
    platform text not null default 'macos-arm64',
    worker_version text not null default '',
    capabilities jsonb not null default '{}'::jsonb,
    last_seen_at timestamptz,
    revoked_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint labor_worker_devices_owner_not_blank check (btrim(owner_user_id) <> '')
);

create index if not exists labor_worker_devices_owner_idx
    on public.labor_worker_devices (owner_user_id, updated_at desc)
    where revoked_at is null;

create table if not exists public.labor_worker_tokens (
    id text primary key,
    device_id text not null,
    owner_user_id text not null,
    token_hash text not null unique,
    expires_at timestamptz not null,
    last_used_at timestamptz,
    revoked_at timestamptz,
    created_at timestamptz not null default now(),
    foreign key (device_id) references public.labor_worker_devices(id) on delete cascade,
    constraint labor_worker_tokens_hash_format check (token_hash ~ '^[0-9a-f]{64}$'),
    constraint labor_worker_tokens_owner_not_blank check (btrim(owner_user_id) <> '')
);

create index if not exists labor_worker_tokens_active_idx
    on public.labor_worker_tokens (token_hash, expires_at)
    where revoked_at is null;
create index if not exists labor_worker_tokens_device_idx
    on public.labor_worker_tokens (device_id, created_at desc);

create table if not exists public.labor_audit_events (
    id bigint generated always as identity primary key,
    run_id text,
    owner_user_id text not null,
    actor_user_id text not null,
    action text not null,
    outcome text not null default 'success',
    reason_code text not null default '',
    details jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    foreign key (run_id) references public.labor_runs(id) on delete set null,
    constraint labor_audit_events_owner_not_blank check (btrim(owner_user_id) <> ''),
    constraint labor_audit_events_actor_not_blank check (btrim(actor_user_id) <> '')
);

create index if not exists labor_audit_events_owner_idx
    on public.labor_audit_events (owner_user_id, created_at desc);
create index if not exists labor_audit_events_run_idx
    on public.labor_audit_events (run_id, created_at desc)
    where run_id is not null;

-- Durable personal Worker queue. The generated columns make security-critical
-- lease fields queryable and indexable without duplicating the compatibility
-- JSON payload consumed by older Workers.
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
    owner_user_id text generated always as (metadata_snapshot ->> 'ownerUserId') stored,
    task_generation_id text generated always as (coalesce(metadata_snapshot ->> 'taskGenerationId', '')) stored,
    required_worker_version_code bigint generated always as (
        coalesce((metadata_snapshot ->> 'requiredWorkerVersionCode')::bigint, 0)
    ) stored,
    worker_id text,
    lease_expires_at timestamptz,
    heartbeat_at timestamptz,
    error_code text,
    error_detail text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    started_at timestamptz,
    finished_at timestamptz,
    constraint labor_jobs_run_fk foreign key (run_id) references public.labor_runs(id) on delete cascade,
    constraint labor_jobs_status_check check (status in ('queued', 'running', 'retry_wait', 'succeeded', 'failed')),
    constraint labor_jobs_attempt_check check (attempt >= 0 and max_attempts >= 1 and attempt <= max_attempts),
    constraint labor_jobs_type_check check (job_type in ('reconcile', 'mapping_preflight')),
    constraint labor_jobs_owner_not_blank check (btrim(owner_user_id) <> '')
);

-- Preserve legacy queue rows that cannot satisfy the new run foreign key.
-- They are removed from the active queue only after their complete original
-- row has been archived as JSON in the same transaction.
create table if not exists public.labor_legacy_job_orphans (
    job_id text primary key,
    archive_reason text not null,
    row_snapshot jsonb not null,
    archived_at timestamptz not null default now()
);

insert into public.labor_legacy_job_orphans (
    job_id, archive_reason, row_snapshot, archived_at
)
select jobs.id, 'missing_labor_run', to_jsonb(jobs), now()
from public.labor_jobs as jobs
where not exists (
    select 1 from public.labor_runs as runs where runs.id=jobs.run_id
)
on conflict (job_id) do update
set archive_reason=excluded.archive_reason,
    row_snapshot=excluded.row_snapshot,
    archived_at=excluded.archived_at;

delete from public.labor_jobs as jobs
where not exists (
    select 1 from public.labor_runs as runs where runs.id=jobs.run_id
);

-- Upgrade the earlier P0 queue in place when it already exists.
alter table public.labor_jobs
    add column if not exists job_type text not null default 'reconcile';

-- Legacy queue rows predate owner-scoped Worker credentials. Bind every
-- existing job to the authoritative run owner before generating/indexing the
-- owner column. Orphaned jobs deliberately remain invalid and make the final
-- constraint validation roll back the entire migration.
update public.labor_jobs as jobs
set metadata_snapshot=jsonb_set(
    coalesce(jobs.metadata_snapshot, '{}'::jsonb),
    '{ownerUserId}',
    to_jsonb(runs.owner_user_id),
    true
)
from public.labor_runs as runs
where jobs.run_id=runs.id
  and coalesce(jobs.metadata_snapshot ->> 'ownerUserId', '')='';

alter table public.labor_jobs
    add column if not exists owner_user_id text generated always as (metadata_snapshot ->> 'ownerUserId') stored;
alter table public.labor_jobs
    add column if not exists task_generation_id text generated always as (coalesce(metadata_snapshot ->> 'taskGenerationId', '')) stored;
alter table public.labor_jobs
    add column if not exists required_worker_version_code bigint generated always as (
        coalesce((metadata_snapshot ->> 'requiredWorkerVersionCode')::bigint, 0)
    ) stored;

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conrelid='public.labor_jobs'::regclass and conname='labor_jobs_run_fk'
    ) then
        alter table public.labor_jobs
            add constraint labor_jobs_run_fk
            foreign key (run_id) references public.labor_runs(id) on delete cascade not valid;
    end if;
    if not exists (
        select 1 from pg_constraint
        where conrelid='public.labor_jobs'::regclass and conname='labor_jobs_type_check'
    ) then
        alter table public.labor_jobs
            add constraint labor_jobs_type_check
            check (job_type in ('reconcile', 'mapping_preflight')) not valid;
    end if;
    if not exists (
        select 1 from pg_constraint
        where conrelid='public.labor_jobs'::regclass and conname='labor_jobs_owner_not_blank'
    ) then
        alter table public.labor_jobs
            add constraint labor_jobs_owner_not_blank
            check (btrim(owner_user_id) <> '') not valid;
    end if;
end $$;

-- These validations deliberately fail the migration if legacy P0 rows do not
-- reference a migrated run or have no owner. Repair/backfill those rows first;
-- never mark an incomplete schema as P1-ready.
alter table public.labor_jobs validate constraint labor_jobs_run_fk;
alter table public.labor_jobs validate constraint labor_jobs_type_check;
alter table public.labor_jobs validate constraint labor_jobs_owner_not_blank;

create unique index if not exists labor_jobs_one_active_run_idx
    on public.labor_jobs (run_id)
    where status in ('queued', 'running', 'retry_wait');
create index if not exists labor_jobs_owner_claim_idx
    on public.labor_jobs (owner_user_id, priority desc, available_at, created_at)
    where status in ('queued', 'running', 'retry_wait');
create index if not exists labor_jobs_generation_idx
    on public.labor_jobs (run_id, task_generation_id, updated_at desc);

comment on table public.labor_jobs is
    'Claim candidates are selected atomically with FOR UPDATE SKIP LOCKED by the private API service.';

-- No browser or Worker receives direct table rights. RLS remains a second
-- boundary for Supabase-style deployments; the private server role must own
-- these tables or have BYPASSRLS.
alter table public.labor_runs enable row level security;
alter table public.labor_run_files enable row level security;
alter table public.labor_workbook_mappings enable row level security;
alter table public.labor_business_reviews enable row level security;
alter table public.labor_worker_devices enable row level security;
alter table public.labor_worker_tokens enable row level security;
alter table public.labor_audit_events enable row level security;
alter table public.labor_jobs enable row level security;
alter table public.labor_legacy_job_orphans enable row level security;
alter table public.labor_schema_versions enable row level security;

revoke all on public.labor_runs from public;
revoke all on public.labor_run_files from public;
revoke all on public.labor_workbook_mappings from public;
revoke all on public.labor_business_reviews from public;
revoke all on public.labor_worker_devices from public;
revoke all on public.labor_worker_tokens from public;
revoke all on public.labor_audit_events from public;
revoke all on public.labor_jobs from public;
revoke all on public.labor_legacy_job_orphans from public;
revoke all on public.labor_schema_versions from public;

do $$
declare
    role_name text;
    table_name text;
begin
    foreach role_name in array array['anon', 'authenticated'] loop
        if exists (select 1 from pg_roles where rolname = role_name) then
            foreach table_name in array array[
                'labor_runs', 'labor_run_files', 'labor_workbook_mappings',
                'labor_business_reviews', 'labor_worker_devices',
                'labor_worker_tokens', 'labor_audit_events', 'labor_jobs',
                'labor_legacy_job_orphans', 'labor_schema_versions'
            ] loop
                execute format('revoke all on table public.%I from %I', table_name, role_name);
            end loop;
        end if;
    end loop;
end $$;

insert into public.labor_schema_versions (component, version, applied_at)
values ('labor_p1', 1, now())
on conflict (component) do update
set version=excluded.version, applied_at=excluded.applied_at;

commit;
