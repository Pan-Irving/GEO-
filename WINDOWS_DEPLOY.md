# Windows 部署说明

本压缩包用于在 Windows 上部署 GEO 撰文工具和发布工作台。

如果要使用 MySQL 部署，优先阅读 `WINDOWS_MYSQL_DEPLOY_GUIDE.md`；本文保留为 Windows 单机部署快速说明。

本包不包含：

- `app-data/` 历史项目数据
- `.env` 密钥配置
- Python 虚拟环境
- `node_modules`
- 本地缓存和构建缓存

Windows 电脑第一次部署需要联网安装依赖。

## 1. 准备环境

请先安装：

- Python 3.11 或更高版本
- Node.js 20 LTS 或更高版本
- Chrome 或 Edge 浏览器

在 PowerShell 中检查：

```powershell
python --version
node --version
npm --version
```

如果 PowerShell 不允许运行脚本，先执行一次：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## 2. 解压项目

把压缩包解压到一个路径较短、不要包含特殊符号的位置，例如：

```text
D:\geo-writing-agent
```

后续命令都在解压后的项目根目录执行。

## 3. 安装依赖

进入项目根目录，执行：

```powershell
.\scripts\install-windows.ps1
```

这个脚本会：

- 根据 `.env.example` 创建 `.env`
- 创建 `backend\.venv`
- 创建 `publishing\backend\.venv`
- 安装主撰文后台 Python 依赖
- 安装发布后台 Python 依赖
- 安装主前端 npm 依赖
- 安装发布前端 npm 依赖

如果依赖安装中断，修复网络或代理问题后，重新执行同一条命令即可。

## 4. 配置 .env

用记事本或 VS Code 打开根目录的 `.env`。

至少填写：

```env
OPENAI_API_KEY=你的写作模型API_KEY
OPENAI_BASE_URL=https://你的中转站地址/v1
OPENAI_MODEL=gpt-5.5
PLANNING_API_KEY=你的规划模型API_KEY
PLANNING_BASE_URL=https://api.deepseek.com
PLANNING_MODEL=deepseek-v4-pro
```

如果没有单独的规划模型 Key，可以先把 `PLANNING_API_KEY` 留空，规划步骤会回退使用 `OPENAI_*` 配置。

图片表格解析相关配置默认已开启：

```env
ENABLE_VISION_OCR=true
ENABLE_LOCAL_OCR=true
OCR_CONCURRENCY=2
IMAGE_OCR_MAX_EDGE=1600
IMAGE_OCR_JPEG_QUALITY=82
```

默认使用本地文件存储：

```env
APP_DATA_DIR=app-data
WRITING_STORAGE_BACKEND=file
PUBLISHING_DATA_DIR=app-data/publishing
```

首次启动后会自动创建新的 `app-data/` 目录。

如果要使用 MySQL 存储项目、文章、审核和发布记录，先阅读并执行：

```text
MYSQL_DEPLOY.md
```

MySQL 模式下，上传原文件和解析后的 Markdown 等文件资产仍然保存在 `APP_DATA_DIR`，不要删除 `app-data/`。

## 5. 启动服务

在项目根目录执行：

```powershell
.\scripts\start-all-windows.ps1
```

脚本会打开 4 个 PowerShell 窗口：

- 主撰文后台：`http://127.0.0.1:8000`
- 主撰文前端：`http://127.0.0.1:5173`
- 发布后台：`http://127.0.0.1:8010`
- 发布工作台前端：`http://127.0.0.1:5174`

浏览器会自动打开：

```text
http://127.0.0.1:5173
http://127.0.0.1:5174
```

如果浏览器没有自动打开，手动访问上面两个地址即可。

## 6. 停止服务

关闭脚本打开的 4 个 PowerShell 窗口即可停止服务。

## 7. 数据说明

这个包不包含旧电脑上的 `app-data/`。部署到 Windows 后会从空数据开始，新上传资料、解析结果、brief、正文和发布数据都会写入 Windows 本机的 `app-data/`。

如果后续要迁移旧数据，可以单独复制旧电脑的 `app-data/` 到 Windows 项目根目录。

## 8. 常见问题

如果提示找不到 `python`、`node` 或 `npm`，重新安装 Python 或 Node.js，并确认安装时勾选了加入 PATH。

如果提示 `node_modules not found`，重新执行：

```powershell
.\scripts\install-windows.ps1
```

如果 API 调用失败，优先检查 `.env` 里的 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL` 是否正确。

如果端口被占用，先关闭旧的 PowerShell 服务窗口，或结束占用 `8000`、`8010`、`5173`、`5174` 的进程后重新启动。
