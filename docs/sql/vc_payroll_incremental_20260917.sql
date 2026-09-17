-- vc_payroll 生产增量（MySQL 5.7）
-- 基线：/Users/zt21197/Downloads/vc_payroll_schema_20260917_1354.sql
-- 目标：当前仓库 bonus_platform/engine/admin_store.py 权限库 schema
--
-- 安全约定：
-- 1. 不 DROP / TRUNCATE / DELETE 业务数据
-- 2. 可重复执行（缺什么补什么）
-- 3. 不改已有列类型，避免锁表和隐式转换
-- 4. 不写入演示账号；仅补模块 / 角色 / 权限 / 公告
-- 5. 不改已有模块的 enabled，避免覆盖生产开关
--
-- 本脚本只覆盖 vc_payroll 里的权限库 + runs。
-- 海外劳务 / FBU / 社保的 Postgres/对象存储不在这个库。

USE `vc_payroll`;

-- ---------------------------------------------------------------------------
-- helpers: MySQL 5.7 没有 ADD COLUMN IF NOT EXISTS
-- ---------------------------------------------------------------------------
SET @db := DATABASE();

-- admin_users.feishu_user_id
SET @exist := (
  SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = @db AND table_name = 'admin_users' AND column_name = 'feishu_user_id'
);
SET @sql := IF(@exist = 0,
  'ALTER TABLE `admin_users` ADD COLUMN `feishu_user_id` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL',
  'SELECT ''skip admin_users.feishu_user_id'' AS msg'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- admin_users.employee_number
SET @exist := (
  SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = @db AND table_name = 'admin_users' AND column_name = 'employee_number'
);
SET @sql := IF(@exist = 0,
  'ALTER TABLE `admin_users` ADD COLUMN `employee_number` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL',
  'SELECT ''skip admin_users.employee_number'' AS msg'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- admin_users.directory_scope
SET @exist := (
  SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = @db AND table_name = 'admin_users' AND column_name = 'directory_scope'
);
SET @sql := IF(@exist = 0,
  'ALTER TABLE `admin_users` ADD COLUMN `directory_scope` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT ''external''',
  'SELECT ''skip admin_users.directory_scope'' AS msg'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- admin_users.directory_synced_at
SET @exist := (
  SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = @db AND table_name = 'admin_users' AND column_name = 'directory_synced_at'
);
SET @sql := IF(@exist = 0,
  'ALTER TABLE `admin_users` ADD COLUMN `directory_synced_at` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL',
  'SELECT ''skip admin_users.directory_synced_at'' AS msg'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- unique: 非空飞书 user id 不能重复；MySQL UNIQUE 允许多个 NULL
SET @exist := (
  SELECT COUNT(*) FROM information_schema.statistics
  WHERE table_schema = @db AND table_name = 'admin_users' AND index_name = 'idx_admin_users_feishu_user_id'
);
SET @sql := IF(@exist = 0,
  'ALTER TABLE `admin_users` ADD UNIQUE KEY `idx_admin_users_feishu_user_id` (`feishu_user_id`)',
  'SELECT ''skip idx_admin_users_feishu_user_id'' AS msg'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ---------------------------------------------------------------------------
-- new tables
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `admin_departments` (
  `id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `parent_id` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `root_id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `synced_at` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_admin_departments_root_id` (`root_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `admin_user_departments` (
  `user_id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `department_id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_primary` tinyint(4) NOT NULL DEFAULT '0',
  `synced_at` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`user_id`,`department_id`),
  KEY `department_id` (`department_id`),
  CONSTRAINT `admin_user_departments_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `admin_users` (`id`),
  CONSTRAINT `admin_user_departments_ibfk_2` FOREIGN KEY (`department_id`) REFERENCES `admin_departments` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `admin_notification_outbox` (
  `id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `event_key` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `kind` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `recipient_open_id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `payload_json` json NOT NULL,
  `status` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'pending',
  `attempt_count` int(11) NOT NULL DEFAULT '0',
  `last_error` text COLLATE utf8mb4_unicode_ci,
  `message_id` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `updated_at` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `sent_at` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `event_key` (`event_key`),
  KEY `idx_admin_notification_outbox_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `workbench_feedback` (
  `id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `user_id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `user_name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `user_open_id` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `category` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `module_id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `module_name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `description` text COLLATE utf8mb4_unicode_ci NOT NULL,
  `page_path` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `user_agent` text COLLATE utf8mb4_unicode_ci,
  `created_at` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  KEY `user_id` (`user_id`),
  CONSTRAINT `workbench_feedback_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `admin_users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `workbench_feedback_attachments` (
  `id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `feedback_id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `filename` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL,
  `content_type` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `size_bytes` bigint(20) NOT NULL,
  `content` longblob NOT NULL,
  `created_at` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  KEY `feedback_id` (`feedback_id`),
  CONSTRAINT `workbench_feedback_attachments_ibfk_1` FOREIGN KEY (`feedback_id`) REFERENCES `workbench_feedback` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `workbench_announcements` (
  `id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `kind` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `title` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `content` text COLLATE utf8mb4_unicode_ci NOT NULL,
  `module_id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `module_name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `visual_style` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by_name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `published_at` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  KEY `created_by` (`created_by`),
  CONSTRAINT `workbench_announcements_ibfk_1` FOREIGN KEY (`created_by`) REFERENCES `admin_users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- seed: roles / modules / permissions
-- created_at 只在首次插入时写入；已有行只更新名称和归属
-- ---------------------------------------------------------------------------
SET @now := DATE_FORMAT(UTC_TIMESTAMP(), '%Y-%m-%dT%H:%i:%sZ');

INSERT IGNORE INTO `admin_roles` (`id`,`name`,`module_id`,`is_system`,`created_at`,`updated_at`) VALUES
  ('admin','系统管理员',NULL,1,@now,@now),
  ('recruitmentAdmin','招聘奖金核算管理员','recruitment',0,@now,@now),
  ('employeeAdmin','国内正式工核算管理员','employee',0,@now,@now),
  ('domesticAdmin','国内外包工核算管理员','domestic',0,@now,@now),
  ('fbuAdmin','海外薪酬核算管理员','fbu',0,@now,@now),
  ('overseasAdmin','海外劳务报账核对管理员','overseas',0,@now,@now),
  ('socialInsuranceAdmin','社保报盘管理员','social_insurance',0,@now,@now);

UPDATE `admin_roles` SET `name`='系统管理员', `module_id`=NULL, `is_system`=1, `updated_at`=@now WHERE `id`='admin';
UPDATE `admin_roles` SET `name`='招聘奖金核算管理员', `module_id`='recruitment', `is_system`=0, `updated_at`=@now WHERE `id`='recruitmentAdmin';
UPDATE `admin_roles` SET `name`='国内正式工核算管理员', `module_id`='employee', `is_system`=0, `updated_at`=@now WHERE `id`='employeeAdmin';
UPDATE `admin_roles` SET `name`='国内外包工核算管理员', `module_id`='domestic', `is_system`=0, `updated_at`=@now WHERE `id`='domesticAdmin';
UPDATE `admin_roles` SET `name`='海外薪酬核算管理员', `module_id`='fbu', `is_system`=0, `updated_at`=@now WHERE `id`='fbuAdmin';
UPDATE `admin_roles` SET `name`='海外劳务报账核对管理员', `module_id`='overseas', `is_system`=0, `updated_at`=@now WHERE `id`='overseasAdmin';
UPDATE `admin_roles` SET `name`='社保报盘管理员', `module_id`='social_insurance', `is_system`=0, `updated_at`=@now WHERE `id`='socialInsuranceAdmin';

INSERT IGNORE INTO `admin_modules` (`id`,`name`,`href`,`owner_role_id`,`enabled`,`development_status`,`created_at`,`updated_at`) VALUES
  ('recruitment','全球招聘奖金核算','recruitment.html','recruitmentAdmin',1,'available',@now,@now),
  ('employee','中国区正式工薪酬核算','china-employee-payroll.html','employeeAdmin',1,'available',@now,@now),
  ('domestic','中国区外包工薪酬核算','domestic-labor.html','domesticAdmin',1,'uat',@now,@now),
  ('fbu','FBU美洲绩效奖金核算','fbu-performance.html','fbuAdmin',1,'available',@now,@now),
  ('overseas_payroll','海外薪资工作台','overseas-payroll.html','fbuAdmin',1,'available',@now,@now),
  ('overseas','海外劳务报账核对','overseas-labor.html','overseasAdmin',1,'uat',@now,@now),
  ('social_insurance','社保报盘工作台','social-insurance.html','socialInsuranceAdmin',1,'uat',@now,@now);

UPDATE `admin_modules` SET `name`='全球招聘奖金核算', `href`='recruitment.html', `owner_role_id`='recruitmentAdmin', `development_status`='available', `updated_at`=@now WHERE `id`='recruitment';
UPDATE `admin_modules` SET `name`='中国区正式工薪酬核算', `href`='china-employee-payroll.html', `owner_role_id`='employeeAdmin', `development_status`='available', `updated_at`=@now WHERE `id`='employee';
UPDATE `admin_modules` SET `name`='中国区外包工薪酬核算', `href`='domestic-labor.html', `owner_role_id`='domesticAdmin', `development_status`='uat', `updated_at`=@now WHERE `id`='domestic';
UPDATE `admin_modules` SET `name`='FBU美洲绩效奖金核算', `href`='fbu-performance.html', `owner_role_id`='fbuAdmin', `development_status`='available', `updated_at`=@now WHERE `id`='fbu';
UPDATE `admin_modules` SET `name`='海外薪资工作台', `href`='overseas-payroll.html', `owner_role_id`='fbuAdmin', `development_status`='available', `updated_at`=@now WHERE `id`='overseas_payroll';
UPDATE `admin_modules` SET `name`='海外劳务报账核对', `href`='overseas-labor.html', `owner_role_id`='overseasAdmin', `development_status`='uat', `updated_at`=@now WHERE `id`='overseas';
UPDATE `admin_modules` SET `name`='社保报盘工作台', `href`='social-insurance.html', `owner_role_id`='socialInsuranceAdmin', `development_status`='uat', `updated_at`=@now WHERE `id`='social_insurance';

-- 只给内置角色补内置模块权限，不碰生产里后加的自定义角色。已有行不覆盖。
INSERT IGNORE INTO `admin_role_module_permissions` (`role_id`,`module_id`,`can_enter`,`updated_at`)
SELECT r.`id`, m.`id`,
  CASE
    WHEN r.`id` = 'admin' THEN 1
    WHEN r.`module_id` = m.`id` THEN 1
    WHEN r.`id` = 'fbuAdmin' AND m.`id` = 'overseas_payroll' THEN 1
    ELSE 0
  END,
  @now
FROM `admin_roles` r
JOIN `admin_modules` m
WHERE r.`id` IN (
  'admin','recruitmentAdmin','employeeAdmin','domesticAdmin','fbuAdmin','overseasAdmin','socialInsuranceAdmin'
)
AND m.`id` IN (
  'recruitment','employee','domestic','fbu','overseas_payroll','overseas','social_insurance'
);

INSERT IGNORE INTO `admin_role_feature_permissions` (`role_id`,`feature_id`,`enabled`,`updated_at`)
SELECT r.`id`, f.`feature_id`,
  CASE
    WHEN r.`id` = 'admin' THEN 1
    WHEN f.`feature_id` IN ('enter','import','calculate','review') THEN 1
    ELSE 0
  END,
  @now
FROM `admin_roles` r
JOIN (
  SELECT 'enter' AS feature_id UNION ALL
  SELECT 'import' UNION ALL
  SELECT 'calculate' UNION ALL
  SELECT 'review' UNION ALL
  SELECT 'export' UNION ALL
  SELECT 'archive' UNION ALL
  SELECT 'audit'
) f
WHERE r.`id` IN (
  'admin','recruitmentAdmin','employeeAdmin','domesticAdmin','fbuAdmin','overseasAdmin','socialInsuranceAdmin'
);

-- 一次性：fbuAdmin 进入海外薪资工作台。已做过迁移的环境不会再改管理员后续关掉的权限。
UPDATE `admin_role_module_permissions`
SET `can_enter`=1, `updated_at`=@now
WHERE `role_id`='fbuAdmin'
  AND `module_id`='overseas_payroll'
  AND NOT EXISTS (
    SELECT 1 FROM `admin_audit_logs`
    WHERE `action`='migrate_default_role_module_grant'
      AND `target_type`='module_role'
      AND `target_id`='overseas_payroll:fbuAdmin'
  );

INSERT INTO `admin_audit_logs` (`actor_user_id`,`action`,`target_type`,`target_id`,`detail`,`created_at`)
SELECT 'system','migrate_default_role_module_grant','module_role','overseas_payroll:fbuAdmin','can_enter=true',@now
FROM DUAL
WHERE NOT EXISTS (
  SELECT 1 FROM `admin_audit_logs`
  WHERE `action`='migrate_default_role_module_grant'
    AND `target_type`='module_role'
    AND `target_id`='overseas_payroll:fbuAdmin'
);

-- 公告：created_by 必须已存在。没有 payrollAdmin 时自动跳过，不造演示账号。
INSERT IGNORE INTO `workbench_announcements` (
  `id`,`kind`,`title`,`content`,`module_id`,`module_name`,`visual_style`,`created_by`,`created_by_name`,`published_at`
)
SELECT
  'UPD-LAUNCH-RECRUITMENT-20260820','feature','招聘奖金核算已上线',
  '每月招聘奖金可以在一个页面里完成。\n- 导入本月资料并完成初算\n- 查看差异并确认结果\n- 确认后导出结果，留存本月记录\n> 建议按“导入—检查—确认—留存”的顺序使用。',
  'recruitment','全球招聘奖金核算','sunny', u.`id`,'HRAS 工作台','2026-08-20T01:00:00Z'
FROM `admin_users` u WHERE u.`id`='payrollAdmin' LIMIT 1;

INSERT IGNORE INTO `workbench_announcements` (
  `id`,`kind`,`title`,`content`,`module_id`,`module_name`,`visual_style`,`created_by`,`created_by_name`,`published_at`
)
SELECT
  'UPD-LAUNCH-EMPLOYEE-20260820','feature','正式工餐补核算已开放',
  '正式工模块现已开放餐补核算。\n- 导入集团与 WX 考勤资料\n- 按月份计算餐补\n- 查看缺失、重复等需要核对的记录\n- 确认后导出结果\n> 当前先开放餐补，其他薪酬项目会按计划增加。',
  'employee','中国区正式工薪酬核算','mint', u.`id`,'HRAS 工作台','2026-08-20T01:01:00Z'
FROM `admin_users` u WHERE u.`id`='payrollAdmin' LIMIT 1;

INSERT IGNORE INTO `workbench_announcements` (
  `id`,`kind`,`title`,`content`,`module_id`,`module_name`,`visual_style`,`created_by`,`created_by_name`,`published_at`
)
SELECT
  'UPD-LAUNCH-DOMESTIC-20260820','feature','外包工薪酬核算开放试用',
  '现在可以按月完成外包工考勤和薪酬核算。\n- 导入考勤资料\n- 核算各项薪酬\n- 查看员工明细和需要复核的记录\n- 导出核算结果\n> 目前处于试用阶段，正式使用前请复核结果。',
  'domestic','中国区外包工薪酬核算','blueprint', u.`id`,'HRAS 工作台','2026-08-20T01:02:00Z'
FROM `admin_users` u WHERE u.`id`='payrollAdmin' LIMIT 1;

INSERT IGNORE INTO `workbench_announcements` (
  `id`,`kind`,`title`,`content`,`module_id`,`module_name`,`visual_style`,`created_by`,`created_by_name`,`published_at`
)
SELECT
  'UPD-LAUNCH-FBU-20260820','feature','FBU绩效奖金核算已上线',
  'FBU 每月绩效奖金可以集中处理。\n- 上传当月薪资、全量调薪和上月薪资\n- 查看绩效数据并进行核算检查\n- 在不同页面之间切换时，已上传资料会继续保留\n- 复核后查看最终结果\n> 刷新页面后，上月薪资仍会保留。',
  'fbu','FBU美洲绩效奖金核算','peach', u.`id`,'HRAS 工作台','2026-08-20T01:03:00Z'
FROM `admin_users` u WHERE u.`id`='payrollAdmin' LIMIT 1;

INSERT IGNORE INTO `workbench_announcements` (
  `id`,`kind`,`title`,`content`,`module_id`,`module_name`,`visual_style`,`created_by`,`created_by_name`,`published_at`
)
SELECT
  'UPD-LAUNCH-OVERSEAS-20260820','feature','海外报账核对开放试用',
  '海外劳务报账资料可以在一个页面完成核对。\n- 上传发票和报账表\n- 按员工查看资料是否一致\n- 集中查看金额、工时和人员信息差异\n- 确认后下载核对结果\n> 请先确认发票清晰、报账表信息完整。',
  'overseas','海外劳务报账核对','sunny', u.`id`,'HRAS 工作台','2026-08-20T01:04:00Z'
FROM `admin_users` u WHERE u.`id`='payrollAdmin' LIMIT 1;

-- ---------------------------------------------------------------------------
-- 执行后核对
-- ---------------------------------------------------------------------------
SELECT table_name
FROM information_schema.tables
WHERE table_schema = DATABASE()
ORDER BY table_name;

SELECT column_name, column_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = DATABASE() AND table_name = 'admin_users'
ORDER BY ordinal_position;

SELECT id, name, href, enabled, development_status FROM admin_modules ORDER BY id;
SELECT role_id, module_id, can_enter FROM admin_role_module_permissions WHERE module_id = 'overseas_payroll' ORDER BY role_id;
