-- Windows existing-deployment patch: per-slot Skill candidate management.
-- Run this only against the writing database after taking a backup.
-- All statements are additive and safe to run more than once.

CREATE TABLE IF NOT EXISTS writing_skill_candidates (
  id VARCHAR(64) NOT NULL,
  article_type VARCHAR(120) NOT NULL,
  stage VARCHAR(32) NOT NULL,
  filename VARCHAR(512) NOT NULL,
  stored_name VARCHAR(512) NOT NULL,
  sha256 VARCHAR(128) NOT NULL,
  uploaded_at VARCHAR(64) NOT NULL,
  PRIMARY KEY (id),
  KEY idx_skill_candidates_slot (article_type, stage, uploaded_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS writing_skill_active_slots (
  article_type VARCHAR(120) NOT NULL,
  stage VARCHAR(32) NOT NULL,
  candidate_id VARCHAR(64) NOT NULL,
  updated_at VARCHAR(64) NOT NULL,
  PRIMARY KEY (article_type, stage)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
