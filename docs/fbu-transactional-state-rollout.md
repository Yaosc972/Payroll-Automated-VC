# FBU transactional state rollout

FBU workflow state now uses Supabase Postgres as the production source of truth. Uploaded Excel files and compatibility snapshots remain in Supabase Storage.

## Release order

1. Apply `supabase/migrations/20260821032943_fbu_transactional_state.sql` to the production Supabase project.
2. Confirm the three `sigma_fbu_*` tables and six RPC functions are visible to the service role only.
3. Set `SIGMA_FBU_STATE_BACKEND=postgres` in the server deployment. Keep the existing Supabase Storage variables unchanged.
4. Deploy the application and run the smoke test below before normal use.

Deploying the application before the migration is safe: missing tables or RPCs trigger the Storage compatibility path. Do not set the backend to `storage` after new Postgres writes have begun unless performing an explicit rollback investigation.

## Smoke test

1. Create a test activity and upload attendance, supplemental leave, salary and performance materials.
2. Refresh after every completed upload and confirm completed steps do not revert.
3. Open the same activity in two browser sessions. Confirm different supplemental-leave rows in each session; refresh both and confirm both decisions remain.
4. Continue to calculation and export. Reopen the activity and confirm all six steps and the exported result remain completed.
5. Start an upload in one session and poll it in the other. A completed job must never return to queued or processing.

## Historical activities and rollback

Historical Storage activities are loaded normally. The first read seeds their core and requested sections into Postgres; missing sections are copied lazily when opened. Storage snapshots continue to be written as a rollback copy.

If the migration itself must be rolled back before production writes, unset `SIGMA_FBU_STATE_BACKEND`. After production Postgres writes exist, preserve the tables and investigate before switching sources to avoid exposing an older Storage snapshot.
