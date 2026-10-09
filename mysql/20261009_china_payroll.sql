-- Prepared migration. Production execution requires approval.
CREATE TABLE IF NOT EXISTS sigma_china_payroll_activities (
 environment VARCHAR(64) NOT NULL, id VARCHAR(64) NOT NULL,
 document LONGTEXT NOT NULL,
 PRIMARY KEY (environment, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS sigma_china_payroll_jobs (
 environment VARCHAR(64) NOT NULL, id VARCHAR(64) NOT NULL,
 activity_id VARCHAR(64) NOT NULL, status VARCHAR(16) NOT NULL,
 lease_token VARCHAR(64) NOT NULL DEFAULT '',
 lease_until DOUBLE NOT NULL DEFAULT 0, claims INTEGER NOT NULL DEFAULT 0,
 created_at DOUBLE NOT NULL, document LONGTEXT NOT NULL,
 PRIMARY KEY (environment, id),
 INDEX sigma_china_payroll_claim_idx (environment, status, created_at),
 CONSTRAINT sigma_china_payroll_activity_fk FOREIGN KEY (environment, activity_id)
  REFERENCES sigma_china_payroll_activities(environment, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
