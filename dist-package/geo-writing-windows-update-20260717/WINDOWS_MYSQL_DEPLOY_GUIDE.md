# Windows + MySQL 部署须知

本文用于把 GEO 撰文工具和发布工作台部署到 Windows 电脑或 Windows 服务器。系统包含两套服务：

- GEO 撰文工作台：前端 `5173`，后端 `8000`
- GEO 发布工作台：前端 `5174`，后端 `8010`

压缩包只包含代码、脚本、SQL、Skill 规则和部署文档，不包含 `.env` 密钥、`app-data/` 历史数据、虚拟环境、`node_modules` 和构建缓存。

## 1. 环境准备

Windows 机器需安装：

- Python 3.11 或更高版本，安装时勾选 Add Python to PATH
- Node.js 20 LTS 或更高版本
- MySQL 8.0 或更高版本
- Chrome 或 Edge 浏览器
- 可用的 OpenAI 兼容 API Key

PowerShell 检查：

```powershell
python --version
node --version
npm --version
mysql --version
```

如果 PowerShell 不允许执行脚本，执行一次：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

如果 `mysql --version` 不存在，可以继续用 Navicat、DBeaver、DataGrip 等工具执行 SQL；只是命令行导表命令不能直接使用。

## 2. 解压目录

建议解压到短路径，避免中文、空格和过长目录，例如：

```text
D:\geo-writing-agent
```

后续命令都在项目根目录执行。

## 3. 安装依赖

在项目根目录运行：

```powershell
.\scripts\install-windows.ps1
```

脚本会自动完成：

- 从 `.env.example` 创建 `.env`
- 创建 `backend\.venv`
- 创建 `publishing\backend\.venv`
- 安装两个后端的 Python 依赖
- 安装两个前端的 npm 依赖

如果下载依赖失败，先检查网络、代理或 pip/npm 镜像，然后重复执行同一条命令即可。

## 4. 创建 MySQL 数据库

推荐撰文系统和发布系统分两个库：

```text
geo_writing
geo_publishing
```

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

如果 MySQL 和应用在同一台机器，也可以使用：

```sql
CREATE USER 'geo_user'@'localhost' IDENTIFIED BY 'geo_password';
GRANT ALL PRIVILEGES ON geo_writing.* TO 'geo_user'@'localhost';
GRANT ALL PRIVILEGES ON geo_publishing.* TO 'geo_user'@'localhost';
FLUSH PRIVILEGES;
```

生产环境请把 `geo_password` 改成强密码。如果密码里包含 `@`、`:`、`/`、`#`、`?` 等字符，写入数据库 URL 时必须 URL 编码；不熟悉编码时建议先使用只包含字母、数字、下划线的密码。

## 5. 导入表结构

如果安装了 MySQL 命令行，在项目根目录执行：

```powershell
mysql -u geo_user -p geo_writing < backend\sql\schema.mysql.sql
mysql -u geo_user -p geo_publishing < publishing\backend\sql\schema.mysql.sql
```

如果没有 `mysql` 命令，用数据库管理工具分别打开并执行：

- `backend\sql\schema.mysql.sql`
- `publishing\backend\sql\schema.mysql.sql`

MySQL 版本低于 8.0 时，如果遇到 `utf8mb4_0900_ai_ci` 报错，把 SQL 里的排序规则改成 `utf8mb4_unicode_ci` 后再执行。

如果是在已有 MySQL 旧环境上升级到意图簇版，不要执行整份建表 SQL。先备份数据库，再只执行 `scripts/windows-intent-group-db-patch.sql` 中的最小补字段语句。

## 6. 配置 .env

打开项目根目录 `.env`，至少配置模型和数据库。

模型配置：

```env
OPENAI_API_KEY=你的写作模型API_KEY
OPENAI_BASE_URL=https://你的中转站地址/v1
OPENAI_MODEL=gpt-5.5
OPENAI_API_MODE=chat
OPENAI_STREAM=true

PLANNING_API_KEY=你的规划模型API_KEY
PLANNING_BASE_URL=https://api.deepseek.com
PLANNING_MODEL=deepseek-v4-pro
PLANNING_API_MODE=chat
PLANNING_STREAM=true
PLANNING_TIMEOUT_SECONDS=600
```

如果没有单独的规划模型 Key，可以把 `PLANNING_API_KEY` 留空，规划步骤会回退使用 `OPENAI_*`。

MySQL 配置：

```env
WRITING_STORAGE_BACKEND=mysql
WRITING_DATABASE_URL=mysql+pymysql://geo_user:geo_password@127.0.0.1:3306/geo_writing?charset=utf8mb4
PUBLISHING_DATABASE_URL=mysql+pymysql://geo_user:geo_password@127.0.0.1:3306/geo_publishing?charset=utf8mb4
```

如果 MySQL 在另一台服务器，把 `127.0.0.1` 改成 MySQL 服务器 IP 或域名，并确认防火墙放行 `3306`。

文件存储配置保留：

```env
APP_DATA_DIR=app-data
PUBLISHING_DATA_DIR=app-data/publishing
```

注意：MySQL 只保存结构化数据。上传原文件、解析后的 Markdown、导出 PDF、外部矩阵导入文件等仍保存在 `app-data/`，不要删除。

发布工作台管理员：

```env
PUBLISHING_ADMIN_USERNAME=admin
PUBLISHING_ADMIN_PASSWORD=请改成强密码
PUBLISHING_ADMIN_DISPLAY_NAME=系统管理员
```

本机部署时端口配置保持默认：

```env
FRONTEND_ORIGIN=http://localhost:5173
WRITING_API_BASE_URL=http://127.0.0.1:8000
PUBLISHING_FRONTEND_URL=http://127.0.0.1:5174
VITE_PUBLISHING_API_BASE=http://127.0.0.1:8010
```

如果部署给局域网其他电脑访问，需要把前端 API 地址和后端跨域地址改成服务器局域网 IP，并重启服务。

## 7. 启动服务

在项目根目录运行：

```powershell
.\scripts\start-all-windows.ps1
```

脚本会打开 4 个 PowerShell 窗口：

- 撰文后端：`http://127.0.0.1:8000`
- 撰文前端：`http://127.0.0.1:5173`
- 发布后端：`http://127.0.0.1:8010`
- 发布前端：`http://127.0.0.1:5174`

浏览器访问：

```text
http://127.0.0.1:5173
http://127.0.0.1:5174
```

停止服务：关闭这 4 个 PowerShell 窗口。

## 8. 验证 MySQL 是否生效

启动后检查：

- 撰文工作台能新建项目
- 发布工作台能用管理员账号登录
- MySQL 表中有新数据

可执行：

```sql
SELECT COUNT(*) FROM geo_writing.writing_projects;
SELECT COUNT(*) FROM geo_publishing.users;
SELECT COUNT(*) FROM geo_publishing.publication_records;
```

如果 `WRITING_STORAGE_BACKEND=mysql` 已启用，新建项目后 `geo_writing.writing_projects` 应增加记录。

## 9. 迁移已有数据

如果这是全新 Windows 部署，可以跳过本节。

如果旧机器有 `app-data/`，先复制到 Windows 项目根目录，再迁移。

撰文系统从文件存储迁移到 MySQL：

```powershell
.\backend\.venv\Scripts\python.exe .\scripts\migrate_writing_file_projects_to_mysql.py --dry-run
.\backend\.venv\Scripts\python.exe .\scripts\migrate_writing_file_projects_to_mysql.py
```

发布工作台从 SQLite 迁移到 MySQL：

```powershell
.\publishing\backend\.venv\Scripts\python.exe .\scripts\migrate_publishing_sqlite_to_mysql.py --dry-run
.\publishing\backend\.venv\Scripts\python.exe .\scripts\migrate_publishing_sqlite_to_mysql.py
```

迁移脚本不会删除原始 `app-data/`。如果目标 MySQL 库已有数据，脚本会拒绝写入；确认要写入非空库时再使用 `--force`。

## 10. 回退到本地存储

临时不用 MySQL 时，把 `.env` 改回：

```env
WRITING_STORAGE_BACKEND=file
WRITING_DATABASE_URL=
PUBLISHING_DATABASE_URL=
```

回退后：

- 撰文系统读取 `app-data/projects/`
- 发布工作台读取 `app-data/publishing/publishing.db`
- MySQL 中的数据不会自动同步回本地文件

## 11. 常见问题

`Access denied`：检查 MySQL 用户名、密码、授权 Host，以及是否对两个库都有权限。

`Unknown database`：先创建 `geo_writing` 和 `geo_publishing`。

连接超时：检查 MySQL 服务是否启动、防火墙是否放行 `3306`、`.env` 主机地址是否正确。

端口占用：关闭旧服务窗口，或结束占用 `8000`、`8010`、`5173`、`5174` 的进程。

Python 找不到：重新安装 Python，并确认加入 PATH。

npm 安装失败：检查 Node.js 版本和网络代理，修复后重新运行 `.\scripts\install-windows.ps1`。

API 调用失败：检查 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`、`PLANNING_*` 是否正确；规划步骤通常走 `PLANNING_*`，写作和 OCR 通常走 `OPENAI_*`。

图片或 PDF 解析慢：可以临时降低 `LOCAL_OCR_MAX_PAGES`、`VISION_OCR_MAX_PAGES` 或关闭 `ENABLE_LOCAL_OCR`。

## 12. 交付包内容说明

压缩包应包含：

- `backend/`
- `frontend/`
- `publishing/`
- `mindsun-geo-content-flow/`
- `new_skills/`
- `scripts/`
- `.env.example`
- `README.md`
- `WINDOWS_DEPLOY.md`
- `MYSQL_DEPLOY.md`
- `WINDOWS_MYSQL_DEPLOY_GUIDE.md`
- `DEPLOY.md`
- `部署说明.md`

压缩包不应包含：

- `.env`
- `.git/`
- `app-data/`
- `node_modules/`
- `.venv/`
- `__pycache__/`
- `.pytest_cache/`
- 任何 API Key、数据库密码或历史客户资料
