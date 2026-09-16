-- Keep the existing atomic save and revision checks; change only RPC transport.
-- The argument MUST remain unnamed so PostgREST passes the JSON body directly.
-- https://docs.postgrest.org/en/stable/references/api/functions.html#functions-with-a-single-unnamed-json-parameter
begin;

create or replace function public.sigma_fbu_commit_snapshot_raw(jsonb)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
begin
  return public.sigma_fbu_commit_snapshot(
    p_environment := $1->>'p_environment',
    p_run_id := $1->>'p_run_id',
    p_expected_core_revision := ($1->>'p_expected_core_revision')::bigint,
    p_seed_core := $1->'p_seed_core',
    p_core_data := $1->'p_core_data',
    p_sections := $1->'p_sections'
  );
end;
$$;

revoke all on function public.sigma_fbu_commit_snapshot_raw(jsonb) from public, anon, authenticated;
grant execute on function public.sigma_fbu_commit_snapshot_raw(jsonb) to service_role;
notify pgrst, 'reload schema';

commit;
