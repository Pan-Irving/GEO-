-- GEO 发布工作台 MySQL 表结构
-- 适用于 MySQL 8.0+，数据库建议使用 utf8mb4 字符集。

CREATE TABLE IF NOT EXISTS users (
  id VARCHAR(64) NOT NULL,
  username VARCHAR(120) NOT NULL,
  display_name VARCHAR(120) NOT NULL,
  role VARCHAR(32) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at VARCHAR(64) NOT NULL,
  updated_at VARCHAR(64) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_users_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS sessions (
  token VARCHAR(128) NOT NULL,
  user_id VARCHAR(64) NOT NULL,
  expires_at VARCHAR(64) NOT NULL,
  created_at VARCHAR(64) NOT NULL,
  PRIMARY KEY (token),
  KEY idx_session_user (user_id),
  CONSTRAINT fk_sessions_user_id
    FOREIGN KEY (user_id) REFERENCES users (id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS article_snapshots (
  article_id VARCHAR(191) NOT NULL,
  project_id VARCHAR(191) NOT NULL,
  project_name VARCHAR(255) NOT NULL,
  source_id VARCHAR(191) NOT NULL,
  brief_id VARCHAR(191) NOT NULL,
  keyword VARCHAR(255) NOT NULL,
  article_type VARCHAR(120) NOT NULL,
  title VARCHAR(512) NOT NULL,
  markdown LONGTEXT NOT NULL,
  content_hash VARCHAR(128) NOT NULL,
  article_audited_at VARCHAR(64) NOT NULL,
  writing_updated_at VARCHAR(64) NOT NULL,
  synced_at VARCHAR(64) NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  PRIMARY KEY (article_id),
  KEY idx_article_project (project_id),
  KEY idx_article_project_active (project_id, active),
  KEY idx_article_keyword_type (keyword, article_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS assignments (
  id VARCHAR(64) NOT NULL,
  user_id VARCHAR(64) NOT NULL,
  project_id VARCHAR(191) NOT NULL,
  keywords_json TEXT NOT NULL,
  article_types_json TEXT NOT NULL,
  created_at VARCHAR(64) NOT NULL,
  updated_at VARCHAR(64) NOT NULL,
  PRIMARY KEY (id),
  KEY idx_assignment_user (user_id),
  KEY idx_assignment_project (project_id),
  CONSTRAINT fk_assignments_user_id
    FOREIGN KEY (user_id) REFERENCES users (id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS publication_records (
  id VARCHAR(64) NOT NULL,
  article_id VARCHAR(191) NOT NULL,
  employee_id VARCHAR(64) NOT NULL,
  channel_type VARCHAR(32) NOT NULL,
  media_kind VARCHAR(64) NOT NULL,
  media_category VARCHAR(64) NOT NULL,
  media_name VARCHAR(255) NOT NULL,
  target_ai_platforms_json TEXT NOT NULL,
  reference_url VARCHAR(1024) NOT NULL,
  publish_url VARCHAR(1024) NOT NULL,
  published_at VARCHAR(64) NOT NULL,
  order_id VARCHAR(128) NOT NULL,
  actual_cost FLOAT NOT NULL DEFAULT 0,
  order_status VARCHAR(32) NOT NULL,
  note TEXT NOT NULL,
  article_content_hash VARCHAR(128) NOT NULL,
  created_at VARCHAR(64) NOT NULL,
  updated_at VARCHAR(64) NOT NULL,
  PRIMARY KEY (id),
  KEY idx_publication_article (article_id),
  KEY idx_publication_employee (employee_id),
  CONSTRAINT fk_publication_records_article_id
    FOREIGN KEY (article_id) REFERENCES article_snapshots (article_id),
  CONSTRAINT fk_publication_records_employee_id
    FOREIGN KEY (employee_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
