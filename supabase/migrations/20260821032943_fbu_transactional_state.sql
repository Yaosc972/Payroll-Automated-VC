-- FBU mutable workflow state belongs in Postgres, not shared Storage JSON files.
-- The application uses the service role on the server only. Browser roles receive
-- no table or function grants.

create table if not exists public.sigma_fbu_runs (
  environment text not null,
  run_id text not null,
  core jsonb not null default '{}'::jsonb,
  revision bigint not null default 1 check (revision > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (environment, run_id)
);

create index if not exists sigma_fbu_runs_environment_created_idx
  on public.sigma_fbu_runs (environment, created_at desc);

create table if not exists public.sigma_fbu_run_sections (
  environment text not null,
  run_id text not null,
  section_name text not null,
  data jsonb not null default '{}'::jsonb,
  revision bigint not null default 1 check (revision > 0),
  updated_at timestamptz not null default now(),
  primary key (environment, run_id, section_name),
  foreign key (environment, run_id)
    references public.sigma_fbu_runs (environment, run_id)
    on delete cascade
);

create table if not exists public.sigma_fbu_upload_jobs (
  environment text not null,
  run_id text not null,
  job_id text not null,
  payload jsonb not null default '{}'::jsonb,
  revision bigint not null default 1 check (revision > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (environment, run_id, job_id),
  foreign key (environment, run_id)
    references public.sigma_fbu_runs (environment, run_id)
    on delete cascade
);

create index if not exists sigma_fbu_upload_jobs_updated_idx
  on public.sigma_fbu_upload_jobs (environment, run_id, updated_at desc);

alter table public.sigma_fbu_runs enable row level security;
alter table public.sigma_fbu_run_sections enable row level security;
alter table public.sigma_fbu_upload_jobs enable row level security;

revoke all on table public.sigma_fbu_runs from anon, authenticated;
revoke all on table public.sigma_fbu_run_sections from anon, authenticated;
revoke all on table public.sigma_fbu_upload_jobs from anon, authenticated;
grant select, insert, update, delete on table public.sigma_fbu_runs to service_role;
grant select, insert, update, delete on table public.sigma_fbu_run_sections to service_role;
grant select, insert, update, delete on table public.sigma_fbu_upload_jobs to service_role;

create or replace function public.sigma_fbu_commit_core(
  p_environment text,
  p_run_id text,
  p_seed jsonb,
  p_patch jsonb
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_core jsonb;
  v_revision bigint;
begin
  insert into public.sigma_fbu_runs (environment, run_id, core, revision, created_at, updated_at)
  values (
    p_environment,
    p_run_id,
    coalesce(p_seed, '{}'::jsonb) || coalesce(p_patch, '{}'::jsonb),
    1,
    coalesce(
      nullif(coalesce(p_seed, '{}'::jsonb)->>'created_at', '')::timestamptz,
      now()
    ),
    now()
  )
  on conflict (environment, run_id) do update
    set core = public.sigma_fbu_runs.core || coalesce(p_patch, '{}'::jsonb),
        revision = public.sigma_fbu_runs.revision + 1,
        updated_at = now()
  returning core, revision into v_core, v_revision;

  return jsonb_build_object('data', v_core, 'revision', v_revision);
end;
$$;

create or replace function public.sigma_fbu_replace_section(
  p_environment text,
  p_run_id text,
  p_section_name text,
  p_data jsonb
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_data jsonb;
  v_revision bigint;
begin
  insert into public.sigma_fbu_run_sections (
    environment, run_id, section_name, data, revision, updated_at
  )
  values (p_environment, p_run_id, p_section_name, coalesce(p_data, '{}'::jsonb), 1, now())
  on conflict (environment, run_id, section_name) do update
    set data = excluded.data,
        revision = public.sigma_fbu_run_sections.revision + 1,
        updated_at = now()
  returning data, revision into v_data, v_revision;

  return jsonb_build_object('applied', true, 'data', v_data, 'revision', v_revision);
end;
$$;

create or replace function public.sigma_fbu_cas_core(
  p_environment text,
  p_run_id text,
  p_expected_revision bigint,
  p_seed jsonb,
  p_data jsonb
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_core jsonb;
  v_revision bigint;
begin
  if coalesce(p_expected_revision, 0) = 0 then
    insert into public.sigma_fbu_runs (environment, run_id, core, revision, created_at, updated_at)
    values (
      p_environment,
      p_run_id,
      coalesce(p_seed, '{}'::jsonb) || coalesce(p_data, '{}'::jsonb),
      1,
      coalesce(nullif(coalesce(p_seed, '{}'::jsonb)->>'created_at', '')::timestamptz, now()),
      now()
    )
    on conflict (environment, run_id) do nothing
    returning core, revision into v_core, v_revision;

    if found then
      return jsonb_build_object('applied', true, 'data', v_core, 'revision', v_revision);
    end if;
  else
    update public.sigma_fbu_runs
       set core = coalesce(p_data, '{}'::jsonb),
           revision = revision + 1,
           updated_at = now()
     where environment = p_environment
       and run_id = p_run_id
       and revision = p_expected_revision
    returning core, revision into v_core, v_revision;

    if found then
      return jsonb_build_object('applied', true, 'data', v_core, 'revision', v_revision);
    end if;
  end if;

  select core, revision
    into v_core, v_revision
    from public.sigma_fbu_runs
   where environment = p_environment
     and run_id = p_run_id;

  return jsonb_build_object(
    'applied', false,
    'data', coalesce(v_core, '{}'::jsonb),
    'revision', coalesce(v_revision, 0)
  );
end;
$$;

create or replace function public.sigma_fbu_cas_section(
  p_environment text,
  p_run_id text,
  p_section_name text,
  p_expected_revision bigint,
  p_data jsonb
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_data jsonb;
  v_revision bigint;
begin
  if coalesce(p_expected_revision, 0) = 0 then
    insert into public.sigma_fbu_run_sections (
      environment, run_id, section_name, data, revision, updated_at
    )
    values (p_environment, p_run_id, p_section_name, coalesce(p_data, '{}'::jsonb), 1, now())
    on conflict (environment, run_id, section_name) do nothing
    returning data, revision into v_data, v_revision;

    if found then
      return jsonb_build_object('applied', true, 'data', v_data, 'revision', v_revision);
    end if;
  else
    update public.sigma_fbu_run_sections
       set data = coalesce(p_data, '{}'::jsonb),
           revision = revision + 1,
           updated_at = now()
     where environment = p_environment
       and run_id = p_run_id
       and section_name = p_section_name
       and revision = p_expected_revision
    returning data, revision into v_data, v_revision;

    if found then
      return jsonb_build_object('applied', true, 'data', v_data, 'revision', v_revision);
    end if;
  end if;

  select data, revision
    into v_data, v_revision
    from public.sigma_fbu_run_sections
   where environment = p_environment
     and run_id = p_run_id
     and section_name = p_section_name;

  return jsonb_build_object(
    'applied', false,
    'data', coalesce(v_data, '{}'::jsonb),
    'revision', coalesce(v_revision, 0)
  );
end;
$$;

create or replace function public.sigma_fbu_patch_job(
  p_environment text,
  p_run_id text,
  p_job_id text,
  p_seed jsonb,
  p_patch jsonb,
  p_allowed_from text[] default null
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_payload jsonb;
  v_revision bigint;
  v_status text;
begin
  select payload, revision
    into v_payload, v_revision
    from public.sigma_fbu_upload_jobs
   where environment = p_environment
     and run_id = p_run_id
     and job_id = p_job_id
   for update;

  if not found then
    v_payload := coalesce(p_seed, '{}'::jsonb) || coalesce(p_patch, '{}'::jsonb);
    insert into public.sigma_fbu_upload_jobs (
      environment, run_id, job_id, payload, revision, created_at, updated_at
    )
    values (p_environment, p_run_id, p_job_id, v_payload, 1, now(), now())
    returning payload, revision into v_payload, v_revision;
    return jsonb_build_object('applied', true, 'data', v_payload, 'revision', v_revision);
  end if;

  v_status := coalesce(v_payload->>'status', '');
  if p_allowed_from is not null and not (v_status = any(p_allowed_from)) then
    return jsonb_build_object('applied', false, 'data', v_payload, 'revision', v_revision);
  end if;

  update public.sigma_fbu_upload_jobs
     set payload = v_payload || coalesce(p_patch, '{}'::jsonb),
         revision = revision + 1,
         updated_at = now()
   where environment = p_environment
     and run_id = p_run_id
     and job_id = p_job_id
  returning payload, revision into v_payload, v_revision;

  return jsonb_build_object('applied', true, 'data', v_payload, 'revision', v_revision);
end;
$$;

create or replace function public.sigma_fbu_commit_snapshot(
  p_environment text,
  p_run_id text,
  p_expected_core_revision bigint,
  p_seed_core jsonb,
  p_core_data jsonb,
  p_sections jsonb
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_core jsonb;
  v_core_revision bigint;
  v_run_exists boolean := false;
  v_section_name text;
  v_spec jsonb;
  v_section_data jsonb;
  v_section_revision bigint;
  v_sections jsonb := '{}'::jsonb;
begin
  select core, revision
    into v_core, v_core_revision
    from public.sigma_fbu_runs
   where environment = p_environment
     and run_id = p_run_id
   for update;
  v_run_exists := found;

  if v_run_exists and v_core_revision <> coalesce(p_expected_core_revision, 0) then
    select coalesce(
      jsonb_object_agg(
        requested.section_name,
        jsonb_build_object(
          'data', coalesce(saved.data, '{}'::jsonb),
          'revision', coalesce(saved.revision, 0)
        )
      ),
      '{}'::jsonb
    )
      into v_sections
      from jsonb_object_keys(coalesce(p_sections, '{}'::jsonb))
        as requested(section_name)
      left join public.sigma_fbu_run_sections saved
        on saved.environment = p_environment
       and saved.run_id = p_run_id
       and saved.section_name = requested.section_name;
    return jsonb_build_object(
      'applied', false,
      'data', v_core,
      'revision', v_core_revision,
      'sections', v_sections
    );
  end if;

  if not v_run_exists and coalesce(p_expected_core_revision, 0) <> 0 then
    return jsonb_build_object(
      'applied', false,
      'data', '{}'::jsonb,
      'revision', 0,
      'sections', '{}'::jsonb
    );
  end if;

  if v_run_exists then
    for v_section_name, v_spec in
      select key, value
        from jsonb_each(coalesce(p_sections, '{}'::jsonb))
       order by key
    loop
      select data, revision
        into v_section_data, v_section_revision
        from public.sigma_fbu_run_sections
       where environment = p_environment
         and run_id = p_run_id
         and section_name = v_section_name
       for update;
      if not found then
        v_section_data := '{}'::jsonb;
        v_section_revision := 0;
      end if;
      if not coalesce((v_spec->>'replace')::boolean, false)
         and v_section_revision <> coalesce((v_spec->>'expected_revision')::bigint, 0) then
        select coalesce(
          jsonb_object_agg(
            requested.section_name,
            jsonb_build_object(
              'data', coalesce(saved.data, '{}'::jsonb),
              'revision', coalesce(saved.revision, 0)
            )
          ),
          '{}'::jsonb
        )
          into v_sections
          from jsonb_object_keys(coalesce(p_sections, '{}'::jsonb))
            as requested(section_name)
          left join public.sigma_fbu_run_sections saved
            on saved.environment = p_environment
           and saved.run_id = p_run_id
           and saved.section_name = requested.section_name;
        return jsonb_build_object(
          'applied', false,
          'data', v_core,
          'revision', v_core_revision,
          'sections', v_sections
        );
      end if;
    end loop;

    update public.sigma_fbu_runs
       set core = coalesce(p_core_data, '{}'::jsonb),
           revision = revision + 1,
           updated_at = now()
     where environment = p_environment
       and run_id = p_run_id
    returning core, revision into v_core, v_core_revision;
  else
    insert into public.sigma_fbu_runs (environment, run_id, core, revision, created_at, updated_at)
    values (
      p_environment,
      p_run_id,
      coalesce(p_seed_core, '{}'::jsonb) || coalesce(p_core_data, '{}'::jsonb),
      1,
      coalesce(nullif(coalesce(p_seed_core, '{}'::jsonb)->>'created_at', '')::timestamptz, now()),
      now()
    )
    returning core, revision into v_core, v_core_revision;
  end if;

  for v_section_name, v_spec in
    select key, value
      from jsonb_each(coalesce(p_sections, '{}'::jsonb))
     order by key
  loop
    insert into public.sigma_fbu_run_sections (
      environment, run_id, section_name, data, revision, updated_at
    )
    values (
      p_environment,
      p_run_id,
      v_section_name,
      coalesce(v_spec->'data', '{}'::jsonb),
      1,
      now()
    )
    on conflict (environment, run_id, section_name) do update
      set data = excluded.data,
          revision = public.sigma_fbu_run_sections.revision + 1,
          updated_at = now()
    returning data, revision into v_section_data, v_section_revision;
    v_sections := v_sections || jsonb_build_object(
      v_section_name,
      jsonb_build_object('data', v_section_data, 'revision', v_section_revision)
    );
  end loop;

  return jsonb_build_object(
    'applied', true,
    'data', v_core,
    'revision', v_core_revision,
    'sections', v_sections
  );
end;
$$;

revoke all on function public.sigma_fbu_commit_core(text, text, jsonb, jsonb)
  from public, anon, authenticated;
revoke all on function public.sigma_fbu_replace_section(text, text, text, jsonb)
  from public, anon, authenticated;
revoke all on function public.sigma_fbu_cas_core(text, text, bigint, jsonb, jsonb)
  from public, anon, authenticated;
revoke all on function public.sigma_fbu_cas_section(text, text, text, bigint, jsonb)
  from public, anon, authenticated;
revoke all on function public.sigma_fbu_patch_job(text, text, text, jsonb, jsonb, text[])
  from public, anon, authenticated;
revoke all on function public.sigma_fbu_commit_snapshot(text, text, bigint, jsonb, jsonb, jsonb)
  from public, anon, authenticated;

grant execute on function public.sigma_fbu_commit_core(text, text, jsonb, jsonb)
  to service_role;
grant execute on function public.sigma_fbu_replace_section(text, text, text, jsonb)
  to service_role;
grant execute on function public.sigma_fbu_cas_core(text, text, bigint, jsonb, jsonb)
  to service_role;
grant execute on function public.sigma_fbu_cas_section(text, text, text, bigint, jsonb)
  to service_role;
grant execute on function public.sigma_fbu_patch_job(text, text, text, jsonb, jsonb, text[])
  to service_role;
grant execute on function public.sigma_fbu_commit_snapshot(text, text, bigint, jsonb, jsonb, jsonb)
  to service_role;
