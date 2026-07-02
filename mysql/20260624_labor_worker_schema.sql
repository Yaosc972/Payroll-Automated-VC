-- ============================================================================
-- MySQL 8.x Migration DDL
-- 对应 Supabase (PostgreSQL) 迁移: supabase/migrations/20260624_labor_worker_schema.sql
--
-- Postgres → MySQL 关键差异:
--   timestamptz     → TIMESTAMP
--   jsonb           → JSON
--   gen_random_uuid → UUID()  (MySQL 8.0+)
--   部分索引         → 改为普通索引（MySQL 不支持）
--   pgcrypto        → 不需要（UUID 已内置）
-- ============================================================================

-- 1. 劳务核对运行记录
CREATE TABLE IF NOT EXISTS labor_runs (
    id VARCHAR(255) PRIMARY KEY,
    organization_id VARCHAR(255),
    created_by VARCHAR(255),
    supplier_name VARCHAR(255) NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    currency VARCHAR(10) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'draft',
    stage VARCHAR(50),
    progress TINYINT NOT NULL DEFAULT 0,
    input_manifest_hash VARCHAR(255),
    engine_version VARCHAR(50),
    rules_version VARCHAR(50),
    model_version VARCHAR(50),
    error_code VARCHAR(100),
    error_message TEXT,
    retryable BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    started_at TIMESTAMP NULL,
    finished_at TIMESTAMP NULL,
    -- MySQL 8.0.16+ 支持 CHECK 约束
    CONSTRAINT chk_labor_runs_progress CHECK (progress BETWEEN 0 AND 100)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- 2. 劳务文件元数据
CREATE TABLE IF NOT EXISTS labor_files (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    run_id VARCHAR(255) NOT NULL,
    file_role VARCHAR(100) NOT NULL,
    bucket VARCHAR(255) NOT NULL,
    object_path TEXT NOT NULL,
    original_filename VARCHAR(500) NOT NULL,
    mime_type VARCHAR(255),
    size_bytes BIGINT,
    sha256 CHAR(64),
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    uploaded_at TIMESTAMP NULL,
    verified_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_labor_files_bucket_object (bucket, object_path(255))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- 3. 劳务任务队列
CREATE TABLE IF NOT EXISTS labor_jobs (
    id VARCHAR(255) PRIMARY KEY,
    run_id VARCHAR(255) NOT NULL,
    job_type VARCHAR(50) NOT NULL DEFAULT 'reconcile',
    status VARCHAR(50) NOT NULL DEFAULT 'queued',
    priority INT NOT NULL DEFAULT 100,
    attempt INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 5,
    available_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    worker_id VARCHAR(255),
    lease_expires_at TIMESTAMP NULL,
    heartbeat_at TIMESTAMP NULL,
    error_code VARCHAR(100),
    error_detail TEXT,
    retryable BOOLEAN NOT NULL DEFAULT FALSE,
    metadata_snapshot JSON NOT NULL DEFAULT (JSON_OBJECT()),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP NULL,
    finished_at TIMESTAMP NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    -- MySQL 不支持部分索引，改为普通复合索引
    INDEX idx_labor_jobs_claim (status, available_at, priority, created_at),
    INDEX idx_labor_jobs_running_lease (status, lease_expires_at),
    INDEX idx_labor_jobs_run_id (run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- 4. 劳务任务重试记录
CREATE TABLE IF NOT EXISTS labor_job_attempts (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    job_id VARCHAR(255) NOT NULL,
    attempt_no INT NOT NULL,
    worker_id VARCHAR(255),
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP NULL,
    outcome VARCHAR(50),
    error_code VARCHAR(100),
    error_detail TEXT,
    retryable BOOLEAN,
    UNIQUE KEY uq_labor_job_attempt (job_id, attempt_no),
    FOREIGN KEY (job_id) REFERENCES labor_jobs(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
