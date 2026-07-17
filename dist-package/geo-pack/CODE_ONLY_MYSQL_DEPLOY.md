# MySQL 现有数据代码覆盖部署说明

本文用于把当前代码部署到一套已经在使用 MySQL 的旧环境中。部署包不包含任何业务数据、数据库 dump、`app-data` 文件、`.env` 密钥或旧构建缓存。

## 1. 部署前确认

旧环境需要保留：

- 现有 MySQL 数据库：`geo_writing`、`geo_publishing` 或你实际使用的库名。
- 旧环境 `.env`：里面包含模型 Key、MySQL 连接串、端口等配置。
- 旧环境 `app-data/`：MySQL 只保存结构化数据，上传原文件、解析文件、导出文件等仍可能在 `APP_DATA_DIR` 下。

建议先备份：

```powershell
mysqldump -u 用户名 -p geo_writing > geo_writing_backup.sql
mysqldump -u 用户名 -p geo_publishing > geo_publishing_backup.sql
```

如果没有 `mysqldump`，至少在 MySQL 管理工具里导出一次备份。

## 2. 解压代码包

把无数据部署包解压到新目录，例如：

```text
D:\geo-writing-agent-new
```

不要把压缩包里的内容直接覆盖旧目录，除非已经确认旧目录里的 `.env` 和 `app-data/` 已经备份。

## 3. 复制旧配置

从旧部署目录复制 `.env` 到新目录根目录：

```powershell
copy D:\旧部署目录\.env D:\geo-writing-agent-new\.env
```

确认 `.env` 中至少保留 MySQL 配置：

```env
WRITING_STORAGE_BACKEND=mysql
WRITING_DATABASE_URL=mysql+pymysql://用户:密码@主机:3306/撰文库名?charset=utf8mb4
PUBLISHING_DATABASE_URL=mysql+pymysql://用户:密码@主机:3306/发布库名?charset=utf8mb4
```

如果旧环境设置了非默认 `APP_DATA_DIR`，保持原值不变。若旧环境使用默认 `app-data`，把旧目录的 `app-data/` 复制到新目录，或在 `.env` 中把 `APP_DATA_DIR` 指向旧的绝对路径。

## 4. 不要导入数据

现有 MySQL 环境只做代码覆盖时，不执行以下动作：

- 不导入 `deployment-data/`。
- 不执行 `backend/sql/schema.mysql.sql`。
- 不执行 `publishing/backend/sql/schema.mysql.sql`。
- 不运行任何迁移旧数据到 MySQL 的脚本。

这些动作只用于新库初始化或数据迁移，不适合已有最新数据的环境。

## 5. 意图簇版最小补字段

如果旧环境还是关键词版，先备份两个库，再执行最小补丁。可以参考 `scripts/windows-intent-group-db-patch.sql`，按实际库名分别进入撰文库和发布库执行。

撰文库：

```sql
ALTER TABLE writing_custom_sources
  ADD COLUMN intent_group VARCHAR(255) NOT NULL DEFAULT '' AFTER source_id;
```

发布库：

```sql
ALTER TABLE article_snapshots
  ADD COLUMN intent_group VARCHAR(255) NOT NULL DEFAULT '' AFTER brief_id;

UPDATE article_snapshots
SET intent_group = keyword
WHERE intent_group IS NULL OR intent_group = '';

ALTER TABLE assignments
  ADD COLUMN intent_groups_json TEXT NULL AFTER project_id;
```

如果某条 `ALTER TABLE` 提示字段已存在，跳过该条即可。旧员工分配不要按关键词自动迁移，上线同步后在发布工作台按“意图簇 + 文章类型”重新分配。

如果旧 MySQL 已经膨胀到几十 GB，部署后参考 `MYSQL_SIZE_OPTIMIZATION.md` 和 `scripts/mysql-size-optimization.sql` 做一次冗余索引字段清理、`OPTIMIZE TABLE` 和 binlog 检查。

## 6. 安装依赖

如果新目录没有虚拟环境和前端依赖，重新安装。

撰文后端：

```powershell
cd D:\geo-writing-agent-new
python -m venv backend\.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

发布后端：

```powershell
python -m venv publishing\backend\.venv
.\publishing\backend\.venv\Scripts\python.exe -m pip install -r publishing\backend\requirements.txt
```

撰文前端：

```powershell
cd frontend
npm install
cd ..
```

发布前端：

```powershell
cd publishing\frontend
npm install
cd ..\..
```

## 7. 启动服务

在四个终端分别启动，或使用你旧环境已有的启动方式。

撰文后端：

```powershell
.\scripts\start-backend.ps1
```

撰文前端：

```powershell
.\scripts\start-frontend.ps1
```

发布后端：

```powershell
.\scripts\start-publishing-backend.ps1
```

发布前端：

```powershell
.\scripts\start-publishing-frontend.ps1
```

默认访问地址：

```text
撰文工作台：http://127.0.0.1:5173
发布工作台：http://127.0.0.1:5174
```

## 8. 验证重点

启动后重点检查：

- 项目列表能读取旧 MySQL 数据。
- 自定义文章新增时必须选择意图簇，重启后意图簇不丢。
- Brief 审核页可以单篇/批量删除 Brief。
- 正文审核页可以单篇/批量删除正文。
- 定稿归档页删除正文后，发布平台对应快照和发布记录同步清理。
- 发布工作台同步后按“意图簇 × 文章类型”展示库存。
- 员工账号只看到被分配的意图簇文章。

如果启动时报数据库字段或表缺失，不要直接导入整份 schema 覆盖旧库。先备份数据库，再对照错误信息做最小 SQL 变更。
