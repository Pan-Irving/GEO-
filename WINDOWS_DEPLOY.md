# Windows 部署说明

这个压缩包不包含 `app-data` 项目数据，也不包含 `.env` 密钥、Python 虚拟环境或 `node_modules`。Windows 电脑第一次部署需要联网安装依赖。

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

## 2. 安装依赖

进入解压后的项目根目录，执行：

```powershell
.\scripts\install-windows.ps1
```

这个脚本会：

- 根据 `.env.example` 创建 `.env`
- 创建 `backend\.venv`
- 安装 Python 后端依赖
- 安装前端 npm 依赖

## 3. 配置 API Key

用记事本或 VS Code 打开根目录的 `.env`，至少填写：

```env
OPENAI_API_KEY=你的写作模型API_KEY
OPENAI_BASE_URL=https://你的中转站地址/v1
OPENAI_MODEL=gpt-5.5
PLANNING_API_KEY=你的规划模型API_KEY
PLANNING_BASE_URL=https://api.deepseek.com
PLANNING_MODEL=deepseek-v4-pro
```

如果没有单独的 `PLANNING_API_KEY`，可以先留空，规划步骤会使用 `OPENAI_*` 配置。

## 4. 启动项目

在项目根目录执行：

```powershell
.\scripts\start-all-windows.ps1
```

脚本会打开两个 PowerShell 窗口，分别启动后端和前端，并自动打开：

```text
http://127.0.0.1:5173
```

也可以手动分别启动：

```powershell
.\scripts\start-backend.ps1
.\scripts\start-frontend.ps1
```

## 5. 数据说明

本包没有携带旧电脑上的项目数据。Windows 电脑首次启动后会自动生成新的 `app-data` 目录，用于保存新上传资料、解析结果和生成内容。
