-- MySQL size optimization helper for existing deployments.
-- Run manually after a full database backup.
-- Execute the writing-database section in geo_writing and the publishing-database
-- section in geo_publishing, or switch USE statements to your real database names.

-- 1) Find the largest tables first.
SELECT
  table_schema,
  table_name,
  ROUND((data_length + index_length) / 1024 / 1024, 2) AS total_mb,
  ROUND(data_length / 1024 / 1024, 2) AS data_mb,
  ROUND(index_length / 1024 / 1024, 2) AS index_mb
FROM information_schema.tables
WHERE table_schema IN ('geo_writing', 'geo_publishing')
ORDER BY data_length + index_length DESC;

-- 2) Writing database: remove duplicated article bodies from lightweight index rows.
-- USE geo_writing;
UPDATE writing_content_items
SET markdown = NULL
WHERE step = 'article'
  AND markdown IS NOT NULL
  AND markdown <> '';

UPDATE writing_content_items
SET raw_json = JSON_OBJECT(
  'id', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.id')),
  'article_id', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.article_id')),
  'brief_id', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.brief_id')),
  'source_id', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.source_id')),
  'source_step', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.source_step')),
  'intent_group', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.intent_group')),
  'keyword', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.keyword')),
  'type', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.type')),
  'article_type', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.article_type')),
  'title', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.title')),
  'status', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.status')),
  'article_audit_status', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.article_audit_status')),
  'used', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.used')),
  'revision', JSON_EXTRACT(raw_json, '$.revision'),
  'updated_at', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.updated_at'))
)
WHERE JSON_VALID(raw_json);

UPDATE writing_articles
SET raw_json = JSON_OBJECT(
  'id', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.id')),
  'article_id', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.article_id')),
  'brief_id', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.brief_id')),
  'source_id', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.source_id')),
  'source_step', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.source_step')),
  'intent_group', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.intent_group')),
  'keyword', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.keyword')),
  'type', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.type')),
  'article_type', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.article_type')),
  'title', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.title')),
  'status', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.status')),
  'article_audit_status', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.article_audit_status')),
  'used', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.used')),
  'revision', JSON_EXTRACT(raw_json, '$.revision'),
  'updated_at', JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.updated_at'))
)
WHERE JSON_VALID(raw_json);

-- Optional, more aggressive: brief markdown is also duplicated in writing_steps.output_json.
-- Only run this if nobody relies on querying brief text directly from writing_content_items.
-- UPDATE writing_content_items
-- SET markdown = NULL
-- WHERE step = 'brief'
--   AND markdown IS NOT NULL
--   AND markdown <> '';

-- 3) Reclaim table space after cleanup. This can lock tables; run during maintenance.
-- USE geo_writing;
-- OPTIMIZE TABLE writing_content_items;
-- OPTIMIZE TABLE writing_articles;
-- OPTIMIZE TABLE writing_steps;

-- USE geo_publishing;
-- OPTIMIZE TABLE article_snapshots;
-- OPTIMIZE TABLE publication_records;

-- 4) Check binary logs. Purge only after confirming backups/replication policy.
SHOW BINARY LOGS;
-- PURGE BINARY LOGS BEFORE (NOW() - INTERVAL 3 DAY);
-- SET GLOBAL binlog_expire_logs_seconds = 604800;
