# GEO 撰文系统 MySQL 预置设计

## 当前数据维护方式

撰文系统当前不使用 MySQL，主数据由文件仓储维护：

```text
app-data/projects/{project_id}/project.json
```

每个项目对应一个独立目录：

```text
app-data/projects/{project_id}/
  project.json
  logs.txt
  materials/
  parsed/
  outputs/
  imports/
```

核心数据分布如下：

- `project.json`：项目名称、资料元数据、自定义文章、步骤状态、任务状态。
- `materials/`：上传资料原文件。
- `parsed/`：资料解析结果。
- `outputs/`：内容规划、Brief、正文 Markdown、PDF、ZIP 等导出文件。
- `logs.txt`：项目操作日志。

现有后端入口是 `backend/app/storage/repository.py`，主要通过 `load_project()` / `save_project()` 读写 `project.json`。

## 是否需要立即迁移

当前撰文系统主要由 1-2 人使用，项目数量和单项目文章数量还不大，因此不强制立即启用 MySQL。短期继续使用文件仓储可以减少迁移风险，也不会影响已经接入 MySQL 的发布系统。

建议触发迁移的条件：

- 单项目正文达到几百篇，`project.json` 明显变大或保存变慢。
- 多人同时审核、导入、修改同一个项目。
- 需要跨项目检索正文、关键词、文章类型、审核状态。
- 需要更强的数据审计、权限、备份恢复和统计能力。
- Windows 部署后运营人员长期高频使用撰文后台。

## 设计原则

- 内容生产源与发布业务源分离：撰文系统负责生成、审核、导入定稿；发布状态、采购状态、发布链接以发布系统 MySQL 为准。
- 大文件不入库：上传资料、解析文件、导出 Markdown/PDF/ZIP 继续保存在磁盘，MySQL 只保存路径、hash 和元数据。
- 正文单独表：正文未来会成为检索和同步核心，应独立建表。
- Agent 输出保留 JSON：矩阵、Brief、正文等复杂输出第一版仍保留 JSON 字段，避免一次性拆表过深。
- 接口兼容：`GET /api/projects/{id}` 和 `/api/projects/{id}/publishing/articles` 的响应结构保持不变。
- 可切换：默认继续使用文件仓储，MySQL 仓储先作为预置能力，通过环境变量切换。

## MySQL 表设计

### `writing_projects`

项目主表。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `varchar(191)` PK | 项目 ID，对应现有目录名 |
| `name` | `varchar(255)` | 项目名称 |
| `created_at` | `varchar(64)` | 创建时间，沿用 ISO 字符串 |
| `updated_at` | `varchar(64)` | 更新时间 |
| `deleted_at` | `varchar(64) null` | 软删除时间，第一版可为空 |

建议索引：

```sql
PRIMARY KEY (id),
KEY idx_writing_projects_updated_at (updated_at)
```

### `writing_materials`

资料元数据表，文件本体仍在 `app-data/projects/{project_id}/materials/`。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `varchar(64)` PK | 资料 ID |
| `project_id` | `varchar(191)` | 所属项目 |
| `filename` | `varchar(512)` | 原始文件名 |
| `stored_name` | `varchar(512)` | 磁盘保存文件名 |
| `content_type` | `varchar(120) null` | MIME 类型 |
| `size` | `bigint` | 文件大小 |
| `sha256` | `varchar(128)` | 文件 hash |
| `parsed_path` | `varchar(1024) null` | 解析结果路径 |
| `status` | `varchar(32)` | `uploaded/parsed/failed` |
| `error` | `text null` | 错误信息 |
| `parse_mode` | `varchar(32) null` | 解析模式 |
| `parser_version` | `varchar(64) null` | 解析器版本 |
| `parse_source` | `varchar(32) null` | `fresh/cache/skipped_existing` |
| `parsed_chars` | `int` | 解析字符数 |
| `ocr_pages` | `int` | OCR 页数 |
| `parsed_at` | `varchar(64) null` | 解析完成时间 |
| `created_at` | `varchar(64)` | 创建时间 |
| `updated_at` | `varchar(64)` | 更新时间 |

建议索引：

```sql
PRIMARY KEY (id),
KEY idx_writing_materials_project (project_id),
KEY idx_writing_materials_sha256 (sha256)
```

### `writing_custom_sources`

自定义文章规划表。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `varchar(191)` | 内部 ID，项目内唯一 |
| `project_id` | `varchar(191)` | 所属项目 |
| `source_id` | `varchar(191)` | 规划源 ID |
| `keyword` | `varchar(255)` | 关键词 |
| `article_type` | `varchar(120)` | 文章类型 |
| `title` | `varchar(512)` | 标题 |
| `role` | `varchar(255)` | 默认“用户自定义选题” |
| `brief_focus` | `text` | Brief 方向 |
| `channel` | `varchar(255)` | 推荐渠道 |
| `channels_json` | `json` | 多渠道 |
| `status` | `varchar(32)` | `ready/completed` |
| `raw_json` | `json` | 原始扩展信息 |
| `created_at` | `varchar(64)` | 创建时间 |
| `updated_at` | `varchar(64)` | 更新时间 |

建议约束和索引：

```sql
PRIMARY KEY (project_id, id),
UNIQUE KEY uq_custom_project_source (project_id, source_id),
KEY idx_custom_project_keyword_type (project_id, keyword, article_type)
```

### `writing_steps`

项目流程步骤状态表，对应当前 `project.steps`。

| 字段 | 类型 | 说明 |
|---|---|---|
| `project_id` | `varchar(191)` | 项目 ID |
| `step` | `varchar(32)` | `materials/intake/matrix/breakthrough/brief/article/archive` |
| `status` | `varchar(32)` | `pending/running/completed/confirmed/failed` |
| `input_json` | `json` | 步骤输入 |
| `output_json` | `json` | 步骤完整输出 |
| `error` | `text null` | 错误信息 |
| `confirmed_at` | `varchar(64) null` | 确认时间 |
| `updated_at` | `varchar(64)` | 更新时间 |

建议主键和索引：

```sql
PRIMARY KEY (project_id, step),
KEY idx_writing_steps_status (step, status)
```

第一版继续保留 `output_json`，保证前端返回结构和当前文件仓储一致。

### `writing_jobs`

后台任务表。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `varchar(64)` PK | Job ID |
| `project_id` | `varchar(191)` | 项目 ID |
| `step` | `varchar(32)` | 所属步骤 |
| `status` | `varchar(32)` | `queued/running/cancelling/cancelled/completed/failed` |
| `error` | `text null` | 错误信息 |
| `total_count` | `int` | 总数 |
| `completed_count` | `int` | 完成数 |
| `failed_count` | `int` | 失败数 |
| `skipped_count` | `int` | 跳过数 |
| `current_item` | `varchar(512) null` | 当前处理项 |
| `message` | `text null` | 状态消息 |
| `created_at` | `varchar(64)` | 创建时间 |
| `updated_at` | `varchar(64)` | 更新时间 |

建议索引：

```sql
PRIMARY KEY (id),
KEY idx_writing_jobs_project (project_id),
KEY idx_writing_jobs_status (project_id, status),
KEY idx_writing_jobs_step (project_id, step)
```

### `writing_content_items`

统一内容项索引表，用于矩阵规划、逐词击破、Brief、正文的基础检索。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `varchar(191)` PK | 内部索引 ID，建议格式为 `{project_id}:{step}:{item_id}` |
| `project_id` | `varchar(191)` | 项目 ID |
| `step` | `varchar(32)` | `matrix/breakthrough/brief/article` |
| `source_id` | `varchar(191)` | 来源 ID |
| `source_step` | `varchar(32)` | 来源步骤 |
| `brief_id` | `varchar(191)` | 绑定 Brief |
| `keyword` | `varchar(255)` | 关键词 |
| `article_type` | `varchar(120)` | 文章类型 |
| `title` | `varchar(512)` | 标题 |
| `status` | `varchar(32)` | 状态 |
| `markdown` | `longtext null` | Markdown 内容 |
| `raw_json` | `json` | 原始数据 |
| `revision` | `int` | 版本 |
| `modified_at` | `varchar(64) null` | 修改时间 |
| `updated_at` | `varchar(64)` | 更新时间 |

建议索引：

```sql
PRIMARY KEY (id),
KEY idx_content_project_step (project_id, step),
KEY idx_content_keyword_type (project_id, keyword, article_type),
KEY idx_content_source (project_id, source_id),
KEY idx_content_brief (project_id, brief_id)
```

### `writing_articles`

正文独立表，未来发布同步主要从这里读取。

| 字段 | 类型 | 说明 |
|---|---|---|
| `article_id` | `varchar(191)` | 正文 ID，项目内唯一 |
| `project_id` | `varchar(191)` | 项目 ID |
| `source_id` | `varchar(191)` | 来源规划 ID |
| `source_step` | `varchar(32)` | `matrix/breakthrough/custom/imported` |
| `brief_id` | `varchar(191)` | Brief ID |
| `keyword` | `varchar(255)` | 关键词 |
| `article_type` | `varchar(120)` | 文章类型 |
| `title` | `varchar(512)` | 标题 |
| `markdown` | `longtext` | 正文 Markdown |
| `status` | `varchar(32)` | `completed/failed/stale/running/queued` |
| `article_audit_status` | `varchar(32)` | `approved/rejected/pending` |
| `article_audited_at` | `varchar(64) null` | 审核时间 |
| `content_hash` | `varchar(128)` | 正文内容 hash |
| `used` | `varchar(64)` | 兼容旧字段，发布状态仍以发布系统为准 |
| `review_notes` | `text null` | 审核意见 |
| `raw_json` | `json` | 原始扩展信息 |
| `created_at` | `varchar(64)` | 创建时间 |
| `updated_at` | `varchar(64)` | 更新时间 |

建议索引：

```sql
PRIMARY KEY (project_id, article_id),
KEY idx_articles_project (project_id),
KEY idx_articles_project_keyword_type (project_id, keyword, article_type),
KEY idx_articles_audit (project_id, article_audit_status),
KEY idx_articles_source_step (project_id, source_step),
KEY idx_articles_content_hash (content_hash)
```

### `writing_matrix_import_drafts`

外部内容矩阵 PDF 导入草稿表。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `varchar(64)` PK | 草稿 ID |
| `project_id` | `varchar(191)` | 项目 ID |
| `status` | `varchar(32)` | `queued/running/completed/applied/failed/cancelled` |
| `filename` | `varchar(512)` | 原文件名 |
| `stored_name` | `varchar(512)` | 磁盘文件名 |
| `content_type` | `varchar(120) null` | 文件类型 |
| `size` | `bigint` | 文件大小 |
| `source_path` | `varchar(1024)` | 文件相对路径 |
| `job_id` | `varchar(64) null` | 关联任务 |
| `parsed_chars` | `int` | 解析字符数 |
| `stats_json` | `json` | 统计数据 |
| `warnings_json` | `json` | 提示信息 |
| `output_json` | `json` | 解析输出 |
| `error` | `text null` | 错误 |
| `created_at` | `varchar(64)` | 创建时间 |
| `updated_at` | `varchar(64)` | 更新时间 |
| `applied_at` | `varchar(64) null` | 应用时间 |

建议索引：

```sql
PRIMARY KEY (id),
KEY idx_matrix_import_project (project_id),
KEY idx_matrix_import_status (project_id, status)
```

### `writing_logs`

项目日志表。未来可替代或同步当前 `logs.txt`。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `bigint` PK auto_increment | 日志 ID |
| `project_id` | `varchar(191)` | 项目 ID |
| `message` | `text` | 日志内容 |
| `created_at` | `varchar(64)` | 创建时间 |

建议索引：

```sql
PRIMARY KEY (id),
KEY idx_writing_logs_project_time (project_id, created_at)
```

## 与发布系统联动

撰文系统与发布系统保持独立数据库，不共享表。

```text
writing_articles.article_id
  ↓ /api/projects/{project_id}/publishing/articles
publishing.article_snapshots.article_id
  ↓ 发布记录
publishing.publication_records.article_id
```

联动边界：

- 撰文系统输出已审核正文。
- 发布系统同步正文快照。
- 发布状态、采购状态、发布链接、成本、员工分配以发布系统 MySQL 为准。
- 撰文系统看板只读取发布系统 `usage-summary` 展示统计，不直接写发布业务数据。

## 迁移与切换方案

### 预置配置

已预置环境变量：

```env
WRITING_STORAGE_BACKEND=file
WRITING_DATABASE_URL=mysql+pymysql://user:password@127.0.0.1:3306/geo_writing?charset=utf8mb4
```

默认值：

```text
WRITING_STORAGE_BACKEND=file
```

### 迁移步骤

1. 在 MySQL 创建 `geo_writing` 数据库。
2. 执行撰文系统 Alembic 建表。

```bash
cd backend
WRITING_DATABASE_URL="mysql+pymysql://user:password@127.0.0.1:3306/geo_writing?charset=utf8mb4" PYTHONPATH=. alembic upgrade head
```
3. 运行 dry-run：

```bash
python scripts/migrate_writing_file_projects_to_mysql.py --dry-run
```

4. 确认项目数、资料数、正文数、日志数一致。
5. 正式迁移：

```bash
python scripts/migrate_writing_file_projects_to_mysql.py
```

6. 修改 `.env`：

```env
WRITING_STORAGE_BACKEND=mysql
```

7. 重启撰文后端。

### 回滚方案

切回文件仓储：

```env
WRITING_STORAGE_BACKEND=file
```

重启后端即可继续读取旧 `app-data/projects`。迁移初期不删除旧文件数据。

## 测试计划

### 文件模式回归

- 当前后端测试全部通过。
- 创建项目、上传资料、生成矩阵、生成 Brief、生成正文、审核正文、导入定稿、导出正文不受影响。

### MySQL 模式验证

- `GET /api/projects` 返回项目列表一致。
- `GET /api/projects/{id}` 返回结构与文件模式一致。
- 后台任务状态更新、取消、失败恢复正常。
- 自定义文章批量新增、重复跳过、编辑、删除正常。
- Markdown 定稿导入后进入归档并可同步发布系统。

### 迁移一致性验证

- 现有项目全部导入 MySQL。
- 项目数、资料数、自定义文章数、正文数一致。
- `article_id`、标题、关键词、文章类型、审核状态、Markdown 内容一致。
- 日志可读。
- 导出文件路径仍有效。

### 发布同步验证

- `/api/projects/{project_id}/publishing/articles` 返回结构不变。
- 发布系统手动/自动同步后，文章库存正常更新。
- 发布记录变化后，撰文看板统计仍能读取。

## 实施边界

本设计文档只是预置方案。当前不启用撰文系统 MySQL，不改变运行逻辑。后续真正实施时，再新增：

- SQLAlchemy models
- Alembic migration
- MySQL repository
- 仓储切换工厂
- 文件到 MySQL 的迁移脚本
- MySQL schema SQL 文件

## Assumptions

- MySQL 使用 8.0+。
- 字符集使用 `utf8mb4`。
- 时间字段第一版继续用 ISO 字符串，兼容现有 Pydantic 模型。
- Markdown 使用 `LONGTEXT`。
- JSON 字段使用 MySQL `JSON` 类型。
- 文件资产继续留在 `app-data/projects`，不进入 MySQL。
