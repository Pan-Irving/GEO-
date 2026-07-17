# Windows 旧 MySQL 环境升级到意图簇版部署手册

本文适用于：Windows 电脑上已经部署过旧版 GEO 撰文系统和发布工作台，旧版按“关键词”分类；现在要部署当前“意图簇”版本，并保留旧 MySQL 数据、`.env` 和 `app-data`。

## 0. 关键原则

- 不要直接覆盖旧目录，先解压到新目录。
- 不要覆盖旧 `.env`、`app-data`、MySQL 数据库。
- 不要对旧库执行整份 `backend/sql/schema.mysql.sql` 或 `publishing/backend/sql/schema.mysql.sql`。
- 旧库只执行最小补字段 SQL。
- 先备份并做一次试恢复，再升级。
- 旧员工关键词分配不自动迁移，上线后按“意图簇 + 文章类型”重新分配。

## 1. 停止旧服务

关闭旧部署中 4 个 PowerShell 窗口：

- 撰文后端 `8000`
- 撰文前端 `5173`
- 发布后端 `8010`
- 发布前端 `5174`

如果不确定服务是否还在运行，可以在 PowerShell 查看端口：

```powershell
netstat -ano | findstr ":8000"
netstat -ano | findstr ":8010"
netstat -ano | findstr ":5173"
netstat -ano | findstr ":5174"
```

## 2. 完整备份

假设旧库名是 `geo_writing` 和 `geo_publishing`。如果你的库名不同，替换成实际库名。

创建备份目录：

```powershell
mkdir D:\geo-backup
```

导出两个 MySQL 库：

```powershell
mysqldump -u geo_user -p --single-transaction --routines --triggers --events geo_writing > D:\geo-backup\geo_writing_backup.sql
mysqldump -u geo_user -p --single-transaction --routines --triggers --events geo_publishing > D:\geo-backup\geo_publishing_backup.sql
```

备份旧部署目录里的配置和文件数据：

```powershell
mkdir D:\geo-backup\env-and-app-data
copy D:\旧部署目录\.env D:\geo-backup\env-and-app-data\.env
robocopy D:\旧部署目录\app-data D:\geo-backup\env-and-app-data\app-data /E
```

检查备份文件不是 0KB：

```powershell
dir D:\geo-backup
dir D:\geo-backup\env-and-app-data
```

## 3. 试恢复备份

建议先恢复到临时库，确认备份真的可用。

进入 MySQL 执行：

```sql
CREATE DATABASE geo_writing_restore_test DEFAULT CHARACTER SET utf8mb4;
CREATE DATABASE geo_publishing_restore_test DEFAULT CHARACTER SET utf8mb4;
```

PowerShell 导入临时库：

```powershell
mysql -u geo_user -p geo_writing_restore_test < D:\geo-backup\geo_writing_backup.sql
mysql -u geo_user -p geo_publishing_restore_test < D:\geo-backup\geo_publishing_backup.sql
```

检查能查到数据：

```sql
SELECT COUNT(*) FROM geo_writing_restore_test.writing_projects;
SELECT COUNT(*) FROM geo_publishing_restore_test.article_snapshots;
```

确认无误后可以保留临时库，升级完成后再删除。

## 4. 解压新代码

把本压缩包解压到新目录，例如：

```text
D:\geo-writing-agent-intent
```

不要把压缩包内容直接解到旧目录。

从旧目录复制 `.env`：

```powershell
copy D:\旧部署目录\.env D:\geo-writing-agent-intent\.env
```

如果旧 `.env` 使用默认相对路径 `APP_DATA_DIR=app-data`，把旧 `app-data` 复制到新目录：

```powershell
robocopy D:\旧部署目录\app-data D:\geo-writing-agent-intent\app-data /E
```

如果旧 `.env` 使用绝对路径 `APP_DATA_DIR=D:\xxx\app-data`，保持原值即可，不需要复制。

## 5. 检查 .env

打开新目录 `.env`，确认至少有：

```env
WRITING_STORAGE_BACKEND=mysql
WRITING_DATABASE_URL=mysql+pymysql://用户:密码@主机:3306/撰文库名?charset=utf8mb4
PUBLISHING_DATABASE_URL=mysql+pymysql://用户:密码@主机:3306/发布库名?charset=utf8mb4
WRITING_API_BASE_URL=http://127.0.0.1:8000
VITE_PUBLISHING_API_BASE=http://127.0.0.1:8010
PUBLISHING_FRONTEND_URL=http://127.0.0.1:5174
```

如果给局域网其他电脑访问，把 `127.0.0.1` 改成服务器局域网 IP，并同步检查跨域地址。

## 6. 执行意图簇最小 SQL 补丁

先确认已经完成第 2、3 步备份和试恢复。

打开 `scripts/windows-intent-group-db-patch.sql`，按你的实际库名分两段执行：

撰文库：

```sql
USE geo_writing;

ALTER TABLE writing_custom_sources
  ADD COLUMN intent_group VARCHAR(255) NOT NULL DEFAULT '' AFTER source_id;
```

发布库：

```sql
USE geo_publishing;

ALTER TABLE article_snapshots
  ADD COLUMN intent_group VARCHAR(255) NOT NULL DEFAULT '' AFTER brief_id;

UPDATE article_snapshots
SET intent_group = keyword
WHERE intent_group IS NULL OR intent_group = '';

ALTER TABLE assignments
  ADD COLUMN intent_groups_json TEXT NULL AFTER project_id;
```

如果提示 `Duplicate column name`，说明字段已经存在，跳过那条即可。

不要执行整份建表 SQL 覆盖旧库。

## 7. 安装依赖

在新代码根目录执行：

```powershell
cd D:\geo-writing-agent-intent
```

撰文后端：

```powershell
python -m venv backend\.venv
.\backend\.venv\Scripts\python.exe -m pip install --upgrade pip
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

发布后端：

```powershell
python -m venv publishing\backend\.venv
.\publishing\backend\.venv\Scripts\python.exe -m pip install --upgrade pip
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

## 8. 启动服务

可以一键启动：

```powershell
.\scripts\start-all-windows.ps1
```

也可以分别启动：

```powershell
.\scripts\start-backend.ps1
.\scripts\start-frontend.ps1
.\scripts\start-publishing-backend.ps1
.\scripts\start-publishing-frontend.ps1
```

访问：

```text
撰文工作台：http://127.0.0.1:5173
发布工作台：http://127.0.0.1:5174
```

## 9. 发布工作台重新同步和分配

1. 登录发布工作台管理员账号。
2. 进入管理设置。
3. 选择旧撰文项目，点击同步。
4. 看库存看板是否变成“意图簇 × 文章类型”。
5. 删除或忽略旧关键词分配。
6. 按新“意图簇 + 文章类型”重新给员工分配板块。

## 10. MySQL 体积优化

如果旧库已经膨胀到几十 GB，升级代码不会自动释放旧表空间。先备份，再参考：

```text
MYSQL_SIZE_OPTIMIZATION.md
scripts/mysql-size-optimization.sql
```

建议先运行表大小查询，确认最大的是哪些表。常见大表：

- `writing_steps`
- `writing_content_items`
- `writing_articles`
- `article_snapshots`
- MySQL binlog 文件

清理冗余索引字段后，需要低峰期执行 `OPTIMIZE TABLE` 才能释放 InnoDB 表空间。binlog 需要按你的备份和复制策略单独清理。

## 11. 验收清单

- 撰文端能打开旧项目。
- 旧项目资料、规划、Brief、正文还在。
- 新增自定义文章时选择的是意图簇，不是固定关键词。
- 重启撰文后端后，自定义文章意图簇不丢。
- 发布端能同步撰文项目。
- 发布库存看板按“意图簇 × 文章类型”展示。
- 旧发布记录还在。
- 员工账号只看到被分配的意图簇文章。
- 撰文端能看到发布库里的已使用 / 采购中状态。

## 12. 回滚

如果升级失败：

1. 停止 4 个服务。
2. 切回旧部署目录启动旧版本，或恢复数据库后再启动。
3. 如需恢复数据库，先重建原库，再导入备份：

```powershell
mysql -u geo_user -p geo_writing < D:\geo-backup\geo_writing_backup.sql
mysql -u geo_user -p geo_publishing < D:\geo-backup\geo_publishing_backup.sql
```

4. 把备份的 `.env` 和 `app-data` 放回旧目录：

```powershell
copy D:\geo-backup\env-and-app-data\.env D:\旧部署目录\.env
robocopy D:\geo-backup\env-and-app-data\app-data D:\旧部署目录\app-data /E
```

只要第 2、3 步备份和试恢复做过，回滚风险可控。
