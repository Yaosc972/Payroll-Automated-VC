-- Apply once before setting SIGMA_FBU_STATE_BACKEND=mysql.
-- Idempotent, additive tables; no existing FBU or Supabase data is deleted.
CREATE TABLE IF NOT EXISTS sigma_fbu_runs (
  environment VARCHAR(64) NOT NULL,
  run_id VARCHAR(128) NOT NULL,
  core LONGTEXT NOT NULL,
  revision BIGINT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (environment, run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sigma_fbu_run_sections (
  environment VARCHAR(64) NOT NULL,
  run_id VARCHAR(128) NOT NULL,
  section_name VARCHAR(128) NOT NULL,
  data LONGTEXT NOT NULL,
  revision BIGINT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (environment, run_id, section_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sigma_fbu_upload_jobs (
  environment VARCHAR(64) NOT NULL,
  run_id VARCHAR(128) NOT NULL,
  job_id VARCHAR(128) NOT NULL,
  payload LONGTEXT NOT NULL,
  revision BIGINT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (environment, run_id, job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
