-- Read one activity into session-local tables. No production rows are changed.
-- Temporary objects are removed before returning the timing summary.
do $probe$
declare
  definition text;
  baseline jsonb;
  payload jsonb;
  result jsonb;
  request_body json;
  started timestamptz;
  timings jsonb := '{}'::jsonb;
begin
  create temp table sigma_fbu_runs (like public.sigma_fbu_runs including all) on commit drop;
  create temp table sigma_fbu_run_sections (like public.sigma_fbu_run_sections including all) on commit drop;
  insert into pg_temp.sigma_fbu_runs select * from public.sigma_fbu_runs where environment='production' and run_id='556722ff';
  insert into pg_temp.sigma_fbu_run_sections select * from public.sigma_fbu_run_sections where environment='production' and run_id='556722ff';
  select core into baseline from pg_temp.sigma_fbu_runs;
  select jsonb_object_agg(section_name, jsonb_build_object('data',data,'expected_revision',revision,'replace',true))
    into payload from pg_temp.sigma_fbu_run_sections;
  definition := pg_get_functiondef('public.sigma_fbu_commit_snapshot(text,text,bigint,jsonb,jsonb,jsonb)'::regprocedure);
  definition := replace(definition, 'public.sigma_fbu_', 'pg_temp.sigma_fbu_');
  execute definition;
  started := clock_timestamp();
  select pg_temp.sigma_fbu_commit_snapshot('production','556722ff',revision,baseline,baseline,payload)
    into result from pg_temp.sigma_fbu_runs;
  timings := jsonb_build_object('baseline_ms',extract(epoch from clock_timestamp()-started)*1000,
    'payload_bytes',octet_length(payload::text),'response_bytes',octet_length(result::text),
    'applied',result->'applied');
  select json_build_object('p_environment','production','p_run_id','556722ff',
    'p_expected_core_revision',revision,'p_seed_core',baseline,'p_core_data',baseline,
    'p_sections',payload) into request_body from pg_temp.sigma_fbu_runs;
  started := clock_timestamp();
  execute $request$
    WITH pgrst_source AS (
      SELECT pgrst_call.pgrst_scalar
      FROM (SELECT $1 AS json_data) pgrst_payload,
      LATERAL (SELECT * FROM json_to_record(pgrst_payload.json_data) AS _(
        p_environment text,p_run_id text,p_expected_core_revision bigint,
        p_seed_core jsonb,p_core_data jsonb,p_sections jsonb) LIMIT 1) pgrst_body,
      LATERAL (SELECT pg_temp.sigma_fbu_commit_snapshot(
        pgrst_body.p_environment,pgrst_body.p_run_id,pgrst_body.p_expected_core_revision,
        pgrst_body.p_seed_core,pgrst_body.p_core_data,pgrst_body.p_sections) pgrst_scalar) pgrst_call
    ) SELECT json_agg(pgrst_scalar)->0 FROM pgrst_source
  $request$ into result using request_body;
  timings := timings || jsonb_build_object('api_envelope_ms',extract(epoch from clock_timestamp()-started)*1000);
  execute $overload$
    create function pg_temp.sigma_fbu_commit_snapshot(p_snapshot jsonb)
    returns jsonb language plpgsql security invoker set search_path = '' as $fn$
    begin
      return pg_temp.sigma_fbu_commit_snapshot(
        p_snapshot->>'p_environment',p_snapshot->>'p_run_id',
        (p_snapshot->>'p_expected_core_revision')::bigint,
        p_snapshot->'p_seed_core',p_snapshot->'p_core_data',p_snapshot->'p_sections');
    end;
    $fn$
  $overload$;
  select json_build_object('p_snapshot', json_build_object(
    'p_environment','production','p_run_id','556722ff','p_expected_core_revision',revision,
    'p_seed_core',baseline,'p_core_data',baseline,'p_sections',payload))
    into request_body from pg_temp.sigma_fbu_runs;
  started := clock_timestamp();
  execute $request$
    WITH pgrst_source AS (
      SELECT pgrst_call.pgrst_scalar
      FROM (SELECT $1 AS json_data) pgrst_payload,
      LATERAL (SELECT * FROM json_to_record(pgrst_payload.json_data) AS _(p_snapshot jsonb) LIMIT 1) pgrst_body,
      LATERAL (SELECT pg_temp.sigma_fbu_commit_snapshot(pgrst_body.p_snapshot) pgrst_scalar) pgrst_call
    ) SELECT json_agg(pgrst_scalar)->0 FROM pgrst_source
  $request$ into result using request_body;
  timings := timings || jsonb_build_object('single_argument_ms',extract(epoch from clock_timestamp()-started)*1000,
    'single_argument_applied',result->'applied');
  select json_build_object('p_environment','production','p_run_id','556722ff',
    'p_expected_core_revision',revision,'p_seed_core',baseline,'p_core_data',baseline,
    'p_sections',payload) into request_body from pg_temp.sigma_fbu_runs;
  started := clock_timestamp();
  execute $request$
    WITH pgrst_source AS (
      SELECT pg_temp.sigma_fbu_commit_snapshot($1::jsonb) as pgrst_scalar
    ) SELECT json_agg(pgrst_scalar)->0 FROM pgrst_source
  $request$ into result using request_body;
  timings := timings || jsonb_build_object('raw_json_ms',extract(epoch from clock_timestamp()-started)*1000,
    'raw_json_applied',result->'applied');
  drop function pg_temp.sigma_fbu_commit_snapshot(jsonb);
  drop function pg_temp.sigma_fbu_commit_snapshot(text,text,bigint,jsonb,jsonb,jsonb);
  drop table pg_temp.sigma_fbu_run_sections;
  drop table pg_temp.sigma_fbu_runs;
  perform set_config('fbu.probe_result',timings::text,true);
end;
$probe$;
select current_setting('fbu.probe_result')::jsonb as diagnostic;
