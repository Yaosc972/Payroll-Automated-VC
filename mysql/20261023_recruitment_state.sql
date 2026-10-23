-- Additive recruitment-only state. Objects use the existing private OBS bucket.
CREATE TABLE IF NOT EXISTS sigma_recruitment_state (
 environment VARCHAR(64) NOT NULL,
 revision BIGINT NOT NULL,
 document LONGTEXT NOT NULL,
 PRIMARY KEY (environment)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS sigma_recruitment_versions (
 environment VARCHAR(64) NOT NULL,
 revision BIGINT NOT NULL,
 document LONGTEXT NOT NULL,
 created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY (environment, revision)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS sigma_recruitment_cancellations (
 environment VARCHAR(64) NOT NULL,
 job_id VARCHAR(64) NOT NULL,
 requested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY (environment, job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS sigma_recruitment_browser_jobs (
 environment VARCHAR(64) NOT NULL,
 id VARCHAR(64) NOT NULL,
 request_key VARCHAR(64) NOT NULL,
 request_document LONGTEXT NOT NULL,
 status VARCHAR(16) NOT NULL,
 lease_token VARCHAR(64) NOT NULL DEFAULT '',
 lease_until DOUBLE NOT NULL DEFAULT 0,
 claims INTEGER NOT NULL DEFAULT 0,
 document LONGTEXT NOT NULL,
 created_at DOUBLE NOT NULL,
 PRIMARY KEY (environment, id),
 UNIQUE KEY sigma_recruitment_browser_request (environment, request_key),
 INDEX sigma_recruitment_browser_claim (environment, status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
