# GEO 撰文工具部署说明

这份包用于部署到另一台电脑本地运行。请不要把自己的 `.env` API Key 放进压缩包里；新电脑上按 `.env.example` 重新创建 `.env`。

## 1. 解压后准备

确认新电脑已安装：

- Python 3.11 或更高版本
- Node.js 20 LTS 或更高版本
- npm

进入项目根目录后创建环境变量文件。

macOS / Linux：

```bash
cp .env.example .env
```

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

打开 `.env`，填写：

```env
OPENAI_API_KEY=你的中转站API_KEY
OPENAI_BASE_URL=https://你的中转站地址/v1
OPENAI_MODEL=gpt-5.5
OPENAI_API_MODE=chat
ENABLE_LOCAL_OCR=true
LOCAL_OCR_ENGINE=rapidocr
LOCAL_OCR_MAX_PAGES=4
LOCAL_OCR_MIN_CONFIDENCE=0.35
ENABLE_VISION_OCR=false
```

说明：图片和扫描 PDF 默认使用本地 RapidOCR，不调用 GPT 视觉模型；抽取表、内容矩阵、Brief、正文等 Agent 生成步骤仍需要中转站 LLM。

## 2. 安装依赖

### macOS / Linux

后端：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` 会安装本地 OCR 依赖 `rapidocr-onnxruntime`。Windows 首次安装可能需要几分钟。

前端：

```bash
cd frontend
npm install
```

### Windows PowerShell

后端：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

如果 PowerShell 提示不能执行脚本，先执行一次：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

前端：

```powershell
cd frontend
npm install
```

## 3. 启动

打开两个终端。

### macOS / Linux

终端 1：

```bash
./scripts/start-backend.sh
```

终端 2：

```bash
./scripts/start-frontend.sh
```

### Windows PowerShell

终端 1：

```powershell
.\scripts\start-backend.ps1
```

终端 2：

```powershell
.\scripts\start-frontend.ps1
```

浏览器访问：

```text
http://127.0.0.1:5173
```

## 4. 数据包说明

- `geo-writing-agent-deploy-code-*.zip`：只包含代码和前端构建产物，不含历史项目数据。
- `geo-writing-agent-deploy-with-data-*.zip`：包含 `app-data/`，会带上当前电脑上的项目资料、解析结果和输出文件。

如果要让另一台电脑继续查看和使用当前项目，请使用带 `with-data` 的完整包。

## 5. 常见端口

- 后端：`127.0.0.1:8000`
- 前端：`127.0.0.1:5173`

如果要做内网穿透，一般暴露前端端口 `5173`。但后端仍需要能被前端访问；跨机器访问时需要把 `.env` 里的 `FRONTEND_ORIGIN` 和前端 API 地址按实际域名/端口调整。
