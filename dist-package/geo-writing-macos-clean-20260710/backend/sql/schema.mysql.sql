-- GEO 撰文系统 MySQL 预置表结构
-- 默认不启用；设置 WRITING_STORAGE_BACKEND=mysql 后由后端读写。

CREATE TABLE IF NOT EXISTS writing_projects (
  id VARCHAR(191) NOT NULL,
  name VARCHAR(255) NOT NULL,
  created_at VARCHAR(64) NOT NULL,
  updated_at VARCHAR(64) NOT NULL,
  deleted_at VARCHAR(64) NULL,
  PRIMARY KEY (id),
  KEY idx_writing_projects_updated_at (updated_at),
  KEY idx_writing_projects_deleted_updated (deleted_at, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS writing_materials (
  id VARCHAR(64) NOT NULL,
  project_id VARCHAR(191) NOT NULL,
  filename VARCHAR(512) NOT NULL,
  stored_name VARCHAR(512) NOT NULL,
  content_type VARCHAR(120) NULL,
  size BIGINT NOT NULL DEFAULT 0,
  sha256 VARCHAR(128) NULL,
  parsed_path VARCHAR(1024) NULL,
  status VARCHAR(32) NOT NULL,
  error TEXT NULL,
  parse_mode VARCHAR(32) NULL,
  parser_version VARCHAR(64) NULL,
  parse_source VARCHAR(32) NULL,
  parsed_chars INT NOT NULL DEFAULT 0,
  ocr_pages INT NOT NULL DEFAULT 0,
  parsed_at VARCHAR(64) NULL,
  created_at VARCHAR(64) NOT NULL,
  updated_at VARCHAR(64) NOT NULL,
  PRIMARY KEY (id),
  KEY idx_writing_materials_project (project_id),
  KEY idx_writing_materials_project_created (project_id, created_at),
  KEY idx_writing_materials_sha256 (sha256),
  CONSTRAINT fk_writing_materials_project
    FOREIGN KEY (project_id) REFERENCES writing_projects (id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS writing_custom_sources (
  id VARCHAR(191) NOT NULL,
  project_id VARCHAR(191) NOT NULL,
  source_id VARCHAR(191) NOT NULL,
  intent_group_id VARCHAR(120) NOT NULL DEFAULT '',
  intent_group VARCHAR(255) NOT NULL DEFAULT '',
  keyword VARCHAR(255) NOT NULL,
  article_type VARCHAR(120) NOT NULL,
  title VARCHAR(512) NOT NULL,
  role VARCHAR(255) NOT NULL,
  brief_focus TEXT NOT NULL,
  channel VARCHAR(255) NOT NULL,
  channels_json JSON NOT NULL,
  status VARCHAR(32) NOT NULL,
  raw_json JSON NOT NULL,
  created_at VARCHAR(64) NOT NULL,
  updated_at VARCHAR(64) NOT NULL,
  PRIMARY KEY (project_id, id),
  UNIQUE KEY uq_custom_project_source (project_id, source_id),
  KEY idx_custom_project_created (project_id, created_at),
  KEY idx_custom_project_keyword_type (project_id, keyword, article_type),
  CONSTRAINT fk_writing_custom_sources_project
    FOREIGN KEY (project_id) REFERENCES writing_projects (id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS writing_intent_groups (
  id VARCHAR(120) NOT NULL,
  project_id VARCHAR(191) NOT NULL,
  name VARCHAR(255) NOT NULL,
  aliases_json JSON NOT NULL,
  keywords_json JSON NOT NULL,
  article_count INT NOT NULL DEFAULT 0,
  created_at VARCHAR(64) NOT NULL,
  updated_at VARCHAR(64) NOT NULL,
  PRIMARY KEY (project_id, id),
  KEY idx_intent_groups_project (project_id),
  KEY idx_intent_groups_project_name (project_id, name),
  CONSTRAINT fk_writing_intent_groups_project
    FOREIGN KEY (project_id) REFERENCES writing_projects (id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS writing_steps (
  project_id VARCHAR(191) NOT NULL,
  step VARCHAR(32) NOT NULL,
  status VARCHAR(32) NOT NULL,
  input_json JSON NOT NULL,
  output_json JSON NOT NULL,
  error TEXT NULL,
  confirmed_at VARCHAR(64) NULL,
  updated_at VARCHAR(64) NOT NULL,
  PRIMARY KEY (project_id, step),
  KEY idx_writing_steps_status (step, status),
  CONSTRAINT fk_writing_steps_project
    FOREIGN KEY (project_id) REFERENCES writing_projects (id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS writing_jobs (
  id VARCHAR(64) NOT NULL,
  project_id VARCHAR(191) NOT NULL,
  step VARCHAR(32) NOT NULL,
  status VARCHAR(32) NOT NULL,
  error TEXT NULL,
  total_count INT NOT NULL DEFAULT 0,
  completed_count INT NOT NULL DEFAULT 0,
  failed_count INT NOT NULL DEFAULT 0,
  skipped_count INT NOT NULL DEFAULT 0,
  current_item VARCHAR(512) NULL,
  message TEXT NULL,
  created_at VARCHAR(64) NOT NULL,
  updated_at VARCHAR(64) NOT NULL,
  PRIMARY KEY (id),
  KEY idx_writing_jobs_project (project_id),
  KEY idx_writing_jobs_project_created (project_id, created_at),
  KEY idx_writing_jobs_status (project_id, status),
  KEY idx_writing_jobs_step (project_id, step),
  CONSTRAINT fk_writing_jobs_project
    FOREIGN KEY (project_id) REFERENCES writing_projects (id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS writing_content_items (
  id VARCHAR(191) NOT NULL,
  project_id VARCHAR(191) NOT NULL,
  step VARCHAR(32) NOT NULL,
  source_id VARCHAR(191) NOT NULL,
  source_step VARCHAR(32) NOT NULL,
  brief_id VARCHAR(191) NOT NULL,
  intent_group_id VARCHAR(120) NOT NULL DEFAULT '',
  keyword VARCHAR(255) NOT NULL,
  article_type VARCHAR(120) NOT NULL,
  title VARCHAR(512) NOT NULL,
  status VARCHAR(32) NOT NULL,
  markdown LONGTEXT NULL,
  raw_json JSON NOT NULL,
  revision INT NOT NULL DEFAULT 1,
  modified_at VARCHAR(64) NULL,
  updated_at VARCHAR(64) NOT NULL,
  PRIMARY KEY (id),
  KEY idx_content_project_step (project_id, step),
  KEY idx_content_keyword_type (project_id, keyword, article_type),
  KEY idx_content_source (project_id, source_id),
  KEY idx_content_brief (project_id, brief_id),
  CONSTRAINT fk_writing_content_items_project
    FOREIGN KEY (project_id) REFERENCES writing_projects (id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS writing_articles (
  article_id VARCHAR(191) NOT NULL,
  project_id VARCHAR(191) NOT NULL,
  source_id VARCHAR(191) NOT NULL,
  source_step VARCHAR(32) NOT NULL,
  brief_id VARCHAR(191) NOT NULL,
  intent_group_id VARCHAR(120) NOT NULL DEFAULT '',
  keyword VARCHAR(255) NOT NULL,
  article_type VARCHAR(120) NOT NULL,
  title VARCHAR(512) NOT NULL,
  markdown LONGTEXT NOT NULL,
  status VARCHAR(32) NOT NULL,
  article_audit_status VARCHAR(32) NOT NULL,
  article_audited_at VARCHAR(64) NULL,
  content_hash VARCHAR(128) NOT NULL,
  used VARCHAR(64) NOT NULL,
  review_notes TEXT NULL,
  raw_json JSON NOT NULL,
  created_at VARCHAR(64) NOT NULL,
  updated_at VARCHAR(64) NOT NULL,
  PRIMARY KEY (project_id, article_id),
  KEY idx_articles_project (project_id),
  KEY idx_articles_project_keyword_type (project_id, keyword, article_type),
  KEY idx_articles_audit (project_id, article_audit_status),
  KEY idx_articles_source_step (project_id, source_step),
  KEY idx_articles_content_hash (content_hash),
  CONSTRAINT fk_writing_articles_project
    FOREIGN KEY (project_id) REFERENCES writing_projects (id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS writing_matrix_import_drafts (
  id VARCHAR(64) NOT NULL,
  project_id VARCHAR(191) NOT NULL,
  status VARCHAR(32) NOT NULL,
  filename VARCHAR(512) NOT NULL,
  stored_name VARCHAR(512) NOT NULL,
  content_type VARCHAR(120) NULL,
  size BIGINT NOT NULL DEFAULT 0,
  source_path VARCHAR(1024) NOT NULL,
  job_id VARCHAR(64) NULL,
  parsed_chars INT NOT NULL DEFAULT 0,
  stats_json JSON NOT NULL,
  warnings_json JSON NOT NULL,
  output_json JSON NOT NULL,
  error TEXT NULL,
  created_at VARCHAR(64) NOT NULL,
  updated_at VARCHAR(64) NOT NULL,
  applied_at VARCHAR(64) NULL,
  PRIMARY KEY (id),
  KEY idx_matrix_import_project (project_id),
  KEY idx_matrix_import_status (project_id, status),
  CONSTRAINT fk_writing_matrix_import_drafts_project
    FOREIGN KEY (project_id) REFERENCES writing_projects (id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS writing_logs (
  id BIGINT NOT NULL AUTO_INCREMENT,
  project_id VARCHAR(191) NOT NULL,
  message TEXT NOT NULL,
  created_at VARCHAR(64) NOT NULL,
  PRIMARY KEY (id),
  KEY idx_writing_logs_project_time (project_id, created_at),
  CONSTRAINT fk_writing_logs_project
    FOREIGN KEY (project_id) REFERENCES writing_projects (id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
