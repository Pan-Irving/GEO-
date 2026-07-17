# MySQL 部署说明

本文说明如何把 GEO 撰文工具和发布工作台部署为 MySQL 存储。

默认部署使用本地文件和 SQLite：

- 撰文系统：`WRITING_STORAGE_BACKEND=file`
- 发布工作台：`PUBLISHING_DATABASE_URL` 为空时使用 `app-data/publishing/publishing.db`

启用 MySQL 后：

- 撰文系统的项目、资料索引、任务状态、brief、正文、审核状态等结构化数据写入 MySQL。
- 发布工作台的用户、分配、文章快照、发布记录等结构化数据写入 MySQL。
- 撰文看板会通过 `PUBLISHING_DATABASE_URL` 只读查询发布库，展示定稿文章的已发布和采购中状态；不需要发布后端开放给撰文系统访问。
- 上传原文件、解析后的 Markdown、导入源文件等文件资产仍然保存在 `APP_DATA_DIR` 下，不要删除 `app-data/`。

## 1. 准备 MySQL

建议使用 MySQL 8.0 或更高版本，并使用 `utf8mb4` 字符集。

用 MySQL 管理工具或命令行执行：

```sql
CREATE DATABASE geo_writing
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_0900_ai_ci;

CREATE DATABASE geo_publishing
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_0900_ai_ci;

CREATE USER 'geo_user'@'%' IDENTIFIED BY 'geo_password';
GRANT ALL PRIVILEGES ON geo_writing.* TO 'geo_user'@'%';
GRANT ALL PRIVILEGES ON geo_publishing.* TO 'geo_user'@'%';
FLUSH PRIVILEGES;
```

如果 MySQL 和应用部署在同一台 Windows 电脑，也可以把用户 Host 改成 `'geo_user'@'localhost'`。

## 2. 导入表结构

在项目根目录执行以下命令。

撰文系统：

```powershell
mysql -u geo_user -p geo_writing < backend\sql\schema.mysql.sql
```

发布工作台：

```powershell
mysql -u geo_user -p geo_publishing < publishing\backend\sql\schema.mysql.sql
```

如果没有安装 `mysql` 命令行工具，也可以用 Navicat、DBeaver、DataGrip 等工具分别打开并执行：

- `backend\sql\schema.mysql.sql`
- `publishing\backend\sql\schema.mysql.sql`

## 3. 配置 .env

打开项目根目录 `.env`，设置：

```env
WRITING_STORAGE_BACKEND=mysql
WRITING_DATABASE_URL=mysql+pymysql://geo_user:geo_password@127.0.0.1:3306/geo_writing?charset=utf8mb4
PUBLISHING_DATABASE_URL=mysql+pymysql://geo_user:geo_password@127.0.0.1:3306/geo_publishing?charset=utf8mb4
```

如果 MySQL 在另一台服务器，把 `127.0.0.1` 改成 MySQL 服务器地址。

密码里如果包含 `@`、`:`、`/`、`#`、`?` 等特殊字符，需要做 URL 编码，或者先使用不含特殊字符的数据库密码。

## 4. 新部署启动

新部署没有旧数据时，完成 `.env` 配置后直接启动：

```powershell
.\scripts\start-all-windows.ps1
```

服务启动后访问：

```text
http://127.0.0.1:5173
http://127.0.0.1:5174
```

发布工作台首次启动时会自动创建管理员账号，默认来自 `.env`：

```env
PUBLISHING_ADMIN_USERNAME=admin
PUBLISHING_ADMIN_PASSWORD=admin123
PUBLISHING_ADMIN_DISPLAY_NAME=系统管理员
```

生产环境请修改默认密码。

## 5. 迁移已有撰文数据

如果之前使用本地 `app-data/` 文件存储，并且想迁移到 MySQL，先确认：

- `.env` 中已设置 `WRITING_STORAGE_BACKEND=mysql`
- `.env` 中已设置正确的 `WRITING_DATABASE_URL`
- `app-data/` 还在项目根目录
- 目标 MySQL 表已创建

先做 dry-run：

```powershell
.\backend\.venv\Scripts\python.exe .\scripts\migrate_writing_file_projects_to_mysql.py --dry-run
```

确认项目数量无误后执行迁移：

```powershell
.\backend\.venv\Scripts\python.exe .\scripts\migrate_writing_file_projects_to_mysql.py
```

如果目标库不是空库，脚本会拒绝写入。确认要导入到非空库时使用：

```powershell
.\backend\.venv\Scripts\python.exe .\scripts\migrate_writing_file_projects_to_mysql.py --force
```

只迁移某个项目：

```powershell
.\backend\.venv\Scripts\python.exe .\scripts\migrate_writing_file_projects_to_mysql.py --project-id 项目ID
```

迁移不会修改原始 `app-data/` 文件。

## 6. 迁移已有发布数据

如果之前发布工作台使用 SQLite，默认文件位置是：

```text
app-data\publishing\publishing.db
```

先确认：

- `.env` 中已设置正确的 `PUBLISHING_DATABASE_URL`
- 目标 MySQL 表已创建
- `app-data\publishing\publishing.db` 存在

先做 dry-run：

```powershell
.\publishing\backend\.venv\Scripts\python.exe .\scripts\migrate_publishing_sqlite_to_mysql.py --dry-run
```

确认数量无误后执行迁移：

```powershell
.\publishing\backend\.venv\Scripts\python.exe .\scripts\migrate_publishing_sqlite_to_mysql.py
```

如果 SQLite 文件不在默认位置：

```powershell
.\publishing\backend\.venv\Scripts\python.exe .\scripts\migrate_publishing_sqlite_to_mysql.py --sqlite-path D:\backup\publishing.db
```

如果目标库已有数据，确认覆盖导入时使用：

```powershell
.\publishing\backend\.venv\Scripts\python.exe .\scripts\migrate_publishing_sqlite_to_mysql.py --force
```

## 7. 验证

启动服务后检查：

- 主撰文前端能打开：`http://127.0.0.1:5173`
- 发布工作台能打开：`http://127.0.0.1:5174`
- 新建项目后，`geo_writing.writing_projects` 中能看到记录
- 登录发布工作台后，`geo_publishing.users` 中能看到管理员用户

也可以在 MySQL 中执行：

```sql
SELECT COUNT(*) FROM geo_writing.writing_projects;
SELECT COUNT(*) FROM geo_publishing.users;
SELECT COUNT(*) FROM geo_publishing.publication_records;
```

撰文看板中的“已使用 / 采购中”来自发布库，只要求撰文后端所在机器能连接 `PUBLISHING_DATABASE_URL` 指向的 MySQL 服务。

## 8. 回退到本地存储

如果要临时回退到默认本地文件存储：

```env
WRITING_STORAGE_BACKEND=file
WRITING_DATABASE_URL=
PUBLISHING_DATABASE_URL=
```

回退后，撰文系统读取 `app-data/projects/`，发布工作台读取 `app-data/publishing/publishing.db`。

MySQL 中的数据不会被自动同步回文件存储。

## 9. 常见问题

如果启动时报 `Access denied`，检查 MySQL 用户名、密码、授权 Host 和数据库权限。

如果启动时报 `Unknown database`，先创建 `geo_writing` 和 `geo_publishing` 两个数据库。

如果启动时报连接超时，检查 MySQL 服务是否启动、防火墙是否放行 `3306`、`.env` 中主机地址是否正确。

如果导入 SQL 时报字符集或排序规则错误，MySQL 版本可能低于 8.0。可以把 SQL 里的 `utf8mb4_0900_ai_ci` 改成 `utf8mb4_unicode_ci` 后再导入。

如果迁移脚本提示目标库非空，先确认是否已经导入过数据，避免重复写入；确实要覆盖或合并时再使用 `--force`。
