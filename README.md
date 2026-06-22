# GEO 内容生产与发布工作台

本项目是一套本地部署的 GEO 内容生产系统，包含两个前端和两个后端：

- **GEO 撰文工作台**：上传项目资料，生成项目信息抽取、内容矩阵、逐词击破规划、Brief、正文，并完成正文审核与定稿归档。
- **GEO 发布工作台**：同步撰文系统已审核定稿文章，分配员工，登记自营发布、网媒采购和发布结果。

系统支持默认本地存储，也支持 MySQL 部署。MySQL 模式下，撰文看板会只读查询发布库，展示文章是否已发布、是否采购中。

## 目录结构

```text
.
├── backend/                    # 撰文后端 FastAPI
├── frontend/                   # 撰文前端 React + Vite
├── publishing/backend/         # 发布工作台后端 FastAPI
├── publishing/frontend/        # 发布工作台前端 React + Vite
├── mindsun-geo-content-flow/   # GEO 内容生产 Skill 与提示词规则
├── scripts/                    # Windows/macOS 启动和迁移脚本
├── backend/sql/                # 撰文 MySQL DDL
├── publishing/backend/sql/     # 发布 MySQL DDL
├── .env.example                # 环境变量模板
├── WINDOWS_DEPLOY.md           # Windows 部署说明
└── MYSQL_DEPLOY.md             # MySQL 部署说明
```

运行后会生成 `app-data/`，用于保存上传文件、解析结果、导出文件和默认本地数据。不要手动删除它。

## 环境要求

- Python 3.11 或更高版本
- Node.js 20 LTS 或更高版本
- npm
- Chrome、Edge 或其他现代浏览器
- 可用的 OpenAI 兼容 LLM API Key
- 可选：MySQL 8.0 或更高版本

检查环境：

```bash
python --version
node --version
npm --version
```

## 快速启动

### Windows

推荐按 [WINDOWS_DEPLOY.md](./WINDOWS_DEPLOY.md) 操作。首次部署：

```powershell
.\scripts\install-windows.ps1
```

编辑 `.env` 后启动全部服务：

```powershell
.\scripts\start-all-windows.ps1
```

脚本会启动：

- 撰文后端：`http://127.0.0.1:8000`
- 撰文前端：`http://127.0.0.1:5173`
- 发布后端：`http://127.0.0.1:8010`
- 发布前端：`http://127.0.0.1:5174`

### macOS / Linux

复制环境变量：

```bash
cp .env.example .env
```

安装撰文后端：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd ..
```

安装撰文前端：

```bash
cd frontend
npm install
cd ..
```

安装发布后端：

```bash
cd publishing/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd ../..
```

安装发布前端：

```bash
cd publishing/frontend
npm install
cd ../..
```

分别启动四个服务：

```bash
./scripts/start-backend.sh
./scripts/start-frontend.sh
./scripts/start-publishing-backend.sh
./scripts/start-publishing-frontend.sh
```

## 环境变量

首次使用时复制 `.env.example` 为 `.env`，至少填写模型配置：

```env
OPENAI_API_KEY=你的写作模型_API_KEY
OPENAI_BASE_URL=https://你的中转站地址/v1
OPENAI_MODEL=gpt-5.5
OPENAI_API_MODE=chat

PLANNING_API_KEY=你的规划模型_API_KEY
PLANNING_BASE_URL=https://api.deepseek.com
PLANNING_MODEL=deepseek-v4-pro
PLANNING_API_MODE=chat
```

如果没有单独规划模型 Key，可以先留空 `PLANNING_API_KEY`，规划步骤会回退使用 `OPENAI_*`。

常用配置：

```env
ENABLE_LOCAL_OCR=true
ENABLE_VISION_OCR=true
BATCH_GENERATION_CONCURRENCY=3
APP_DATA_DIR=app-data
FRONTEND_ORIGIN=http://localhost:5173
WRITING_API_BASE_URL=http://127.0.0.1:8000
PUBLISHING_FRONTEND_URL=http://127.0.0.1:5174
```

说明：

- `OPENAI_*`：Brief、正文和视觉 OCR 等写作/理解任务使用。
- `PLANNING_*`：项目信息抽取、内容矩阵、逐词击破和外部矩阵 PDF 识别使用。
- `ENABLE_VISION_OCR=true`：图片资料优先用视觉模型识别表格和截图结构。
- `ENABLE_LOCAL_OCR=true`：扫描 PDF 和视觉 OCR 失败时使用本地 OCR。
- `PUBLISHING_FRONTEND_URL`：撰文工作台顶部“发布工作台”按钮跳转地址。部署到其他电脑或内网穿透时改这里，重启撰文后端生效。

## 默认存储模式

默认配置：

```env
WRITING_STORAGE_BACKEND=file
WRITING_DATABASE_URL=
PUBLISHING_DATABASE_URL=
```

含义：

- 撰文项目数据保存在 `app-data/projects/`。
- 发布工作台使用 `app-data/publishing/publishing.db`。
- 上传原文件、解析后的 Markdown 和导出文件保存在 `app-data/`。

默认模式适合单机试用和演示。

## MySQL 部署

生产或多人使用建议启用 MySQL。详见 [MYSQL_DEPLOY.md](./MYSQL_DEPLOY.md)。

推荐使用两个库：

```text
geo_writing     # 撰文系统结构化数据
geo_publishing  # 发布工作台结构化数据
```

`.env` 示例：

```env
WRITING_STORAGE_BACKEND=mysql
WRITING_DATABASE_URL=mysql+pymysql://geo_user:geo_password@127.0.0.1:3306/geo_writing?charset=utf8mb4
PUBLISHING_DATABASE_URL=mysql+pymysql://geo_user:geo_password@127.0.0.1:3306/geo_publishing?charset=utf8mb4
```

导入表结构：

```powershell
mysql -u geo_user -p geo_writing < backend\sql\schema.mysql.sql
mysql -u geo_user -p geo_publishing < publishing\backend\sql\schema.mysql.sql
```

迁移已有撰文文件数据：

```powershell
.\backend\.venv\Scripts\python.exe .\scripts\migrate_writing_file_projects_to_mysql.py --dry-run
.\backend\.venv\Scripts\python.exe .\scripts\migrate_writing_file_projects_to_mysql.py
```

迁移已有发布 SQLite 数据：

```powershell
.\publishing\backend\.venv\Scripts\python.exe .\scripts\migrate_publishing_sqlite_to_mysql.py --dry-run
.\publishing\backend\.venv\Scripts\python.exe .\scripts\migrate_publishing_sqlite_to_mysql.py
```

注意：MySQL 只保存结构化数据。上传原文件、解析文件和导出文件仍在 `APP_DATA_DIR` 下。

## 发布状态联动

撰文看板中的“已使用 / 采购中”来自发布库，只读查询 `PUBLISHING_DATABASE_URL` 指向的发布数据库。

数据关系：

```text
撰文系统审核通过正文
  -> 发布工作台同步为 article_snapshots
  -> 发布工作台登记 publication_records
  -> 撰文看板只读汇总发布状态
```

规则：

- `published` 记录计入“已使用”。
- `purchasing` 记录计入“采购中”。
- 同一篇文章既自营已发布又网媒采购中时，会同时计入“已使用”和“采购中”。
- 不做跨库外键，不把发布状态回写撰文库。

## 主要工作流

### 撰文工作台

1. 创建项目。
2. 上传资料并解析。
3. 生成并确认项目信息。
4. 生成内容矩阵、需求驱动矩阵或逐词击破规划。
5. 勾选规划生成 Brief。
6. 勾选 Brief 生成正文。
7. 审核正文并定稿。
8. 导出 Markdown 或进入发布工作台使用。

支持本地导入 Markdown 定稿，导入后会直接进入定稿归档。

### 发布工作台

1. 管理员登录发布工作台。
2. 从撰文系统同步项目定稿文章。
3. 创建员工账号和分配范围。
4. 员工登记自营发布或网媒采购需求。
5. 管理员回填网媒采购结果。
6. 撰文看板自动展示发布使用状态。

默认管理员由 `.env` 控制：

```env
PUBLISHING_ADMIN_USERNAME=admin
PUBLISHING_ADMIN_PASSWORD=admin123
PUBLISHING_ADMIN_DISPLAY_NAME=系统管理员
```

生产环境请修改默认密码。

## 打包部署到 Windows

当前仓库提供 Windows 脚本：

- `scripts/install-windows.ps1`：安装 Python/npm 依赖。
- `scripts/start-all-windows.ps1`：同时启动四个服务。
- `scripts/start-backend.ps1`：启动撰文后端。
- `scripts/start-frontend.ps1`：启动撰文前端。
- `scripts/start-publishing-backend.ps1`：启动发布后端。
- `scripts/start-publishing-frontend.ps1`：启动发布前端。

打包时不要包含：

- `.env`
- `backend/.venv`
- `publishing/backend/.venv`
- `node_modules`
- `release`

如果要把旧电脑项目文件一起迁移，需要额外复制 `app-data/`。

## 常用验证

检查撰文后端：

```text
http://127.0.0.1:8000/api/agent/health
```

检查撰文项目：

```text
http://127.0.0.1:8000/api/projects
```

MySQL 验证：

```sql
SELECT COUNT(*) FROM geo_writing.writing_projects;
SELECT COUNT(*) FROM geo_writing.writing_articles;
SELECT COUNT(*) FROM geo_publishing.users;
SELECT COUNT(*) FROM geo_publishing.publication_records;
```

前端构建：

```bash
cd frontend && npm run build
cd publishing/frontend && npm run build
```

后端关键测试：

```bash
pytest backend/tests/test_publishing_usage.py backend/tests/test_health_config.py
```

## 常见问题

### 撰文平台是否已经使用 MySQL？

执行：

```bash
python - <<'PY'
import sys
sys.path.insert(0, "backend")
from app.core.config import get_settings
s = get_settings()
print("WRITING_STORAGE_BACKEND =", s.writing_storage_backend)
print("WRITING_DATABASE_URL configured =", bool(s.writing_database_url))
PY
```

如果输出 `WRITING_STORAGE_BACKEND = mysql` 且连接串已配置，说明配置层已切到 MySQL。再新建一个项目，检查 `geo_writing.writing_projects` 是否新增记录即可确认写入成功。

### Navicat 看不到迁移后的数据？

先刷新 `geo_writing` 库和表。迁移脚本里的 `Target table counts: 0` 是导入前计数；看到 `Imported project...` 和 `Migration complete` 才表示写入完成。

### 发布工作台按钮跳错地址？

修改 `.env`：

```env
PUBLISHING_FRONTEND_URL=https://你的发布工作台地址
```

重启撰文后端，刷新浏览器。

### 授权 MySQL 用户时报 1410？

当前 MySQL 账号没有授权能力，或目标用户不存在。可以改用当前可登录 MySQL 的账号配置连接串，或用 root 创建并授权用户。

### 端口被占用？

默认端口是 `8000`、`8010`、`5173`、`5174`。关闭旧服务窗口，或结束占用端口的进程后重启。

