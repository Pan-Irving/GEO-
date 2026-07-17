-- Windows existing-MySQL upgrade patch for the intent-group version.
-- Run after backing up the writing and publishing databases.
-- If a column already exists, skip that ALTER statement.

-- Writing database, for example:
-- USE geo_writing;
ALTER TABLE writing_custom_sources
  ADD COLUMN intent_group VARCHAR(255) NOT NULL DEFAULT '' AFTER source_id;

ALTER TABLE writing_custom_sources
  ADD COLUMN intent_group_id VARCHAR(120) NOT NULL DEFAULT '' AFTER source_id;

ALTER TABLE writing_content_items
  ADD COLUMN intent_group_id VARCHAR(120) NOT NULL DEFAULT '' AFTER brief_id;

ALTER TABLE writing_articles
  ADD COLUMN intent_group_id VARCHAR(120) NOT NULL DEFAULT '' AFTER brief_id;

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

-- Publishing database, for example:
-- USE geo_publishing;
ALTER TABLE article_snapshots
  ADD COLUMN intent_group VARCHAR(255) NOT NULL DEFAULT '' AFTER brief_id;

ALTER TABLE article_snapshots
  ADD COLUMN intent_group_id VARCHAR(120) NOT NULL DEFAULT '' AFTER brief_id;

UPDATE article_snapshots
SET intent_group = keyword
WHERE intent_group IS NULL OR intent_group = '';

ALTER TABLE assignments
  ADD COLUMN intent_groups_json TEXT NULL AFTER project_id;

ALTER TABLE assignments
  ADD COLUMN intent_group_ids_json TEXT NULL AFTER project_id;
