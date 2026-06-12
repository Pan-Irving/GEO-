# GEO 撰文后台 Agent 操作手册

本项目是一个本地运行的 GEO 内容生产工具，面向运营人员使用。它由 Python 后台 Agent 和网页控制台组成，可以读取项目资料，按固定流程生成项目信息抽取表、内容矩阵、逐词击破规划、Brief 和正文，并导出 Markdown 文件。

运营人员不需要修改代码，只需要按本文完成安装、配置、启动和页面操作。

## 1. 电脑准备

请先确认电脑已经安装以下软件。

### 必装软件

- Python 3.11 或更高版本。
- Node.js 20 LTS 或更高版本。
- 一个可用的 LLM 中转站 API Key。
- 一个现代浏览器，例如 Chrome、Edge、Safari。

### 检查是否安装成功

打开终端或 PowerShell，分别输入：

```bash
python --version
node --version
npm --version
```

如果能看到版本号，说明已安装。如果提示找不到命令，需要先安装对应软件。

## 2. 项目目录说明

解压项目后，目录大致如下：

```text
geo-writing-agent/
├── backend/                    # Python 后台 Agent
├── frontend/                   # 网页控制台
├── mindsun-geo-content-flow/   # GEO 内容生产 Skill 规则
├── .env.example                # 环境变量示例
└── README.md                   # 本操作手册
```

运行后会自动生成：

```text
app-data/                       # 项目资料、解析内容、生成结果
```

不要手动删除 `app-data/`。它保存了项目、上传资料和输出文件。

## 3. 配置环境变量

第一次使用时，在项目根目录复制一份环境变量文件：

```bash
cp .env.example .env
```

Windows PowerShell 使用：

```powershell
Copy-Item .env.example .env
```

然后用文本编辑器打开 `.env`，填写中转站配置。

推荐配置：

```env
OPENAI_API_KEY=你的中转站API_KEY
OPENAI_BASE_URL=https://你的中转站地址/v1
OPENAI_MODEL=gpt-5.5
OPENAI_API_MODE=chat
PLANNING_API_KEY=你的DeepSeek_API_KEY
PLANNING_BASE_URL=https://api.deepseek.com
PLANNING_MODEL=deepseek-v4-pro
PLANNING_API_MODE=chat
ENABLE_LOCAL_OCR=true
LOCAL_OCR_ENGINE=rapidocr
LOCAL_OCR_MAX_PAGES=4
LOCAL_OCR_MIN_CONFIDENCE=0.35
ENABLE_VISION_OCR=false
OCR_CONCURRENCY=2
IMAGE_OCR_MAX_EDGE=1600
IMAGE_OCR_JPEG_QUALITY=82
BATCH_GENERATION_CONCURRENCY=3
APP_DATA_DIR=app-data
FRONTEND_ORIGIN=http://localhost:5173
```

说明：

- `OPENAI_API_KEY`：写作模型 API Key，主要用于 Brief 和正文生成。
- `OPENAI_BASE_URL`：写作模型地址；如果使用中转站，通常以 `/v1` 结尾。
- `OPENAI_MODEL`：Brief、正文等写作步骤使用的模型。
- `OPENAI_API_MODE=chat`：适配只支持 `/v1/chat/completions` 的中转站。
- `PLANNING_API_KEY`：规划模型 API Key，建议填写 DeepSeek 官方 Key；为空时规划步骤回退使用 `OPENAI_*`。
- `PLANNING_BASE_URL=https://api.deepseek.com`：规划模型地址。
- `PLANNING_MODEL=deepseek-v4-pro`：intake、内容矩阵、逐词击破和外部矩阵 PDF 识别使用的规划模型。
- `PLANNING_API_MODE=chat`：DeepSeek 官方 OpenAI 兼容接口使用 `chat`。
- `ENABLE_LOCAL_OCR=true`：开启本地 OCR，图片和扫描 PDF 不调用 GPT。
- `LOCAL_OCR_ENGINE=rapidocr`：本地 OCR 引擎，使用 RapidOCR + ONNXRuntime，支持 Windows/macOS。
- `LOCAL_OCR_MAX_PAGES=4`：智能快速模式下扫描 PDF 最多 OCR 页数。
- `LOCAL_OCR_MIN_CONFIDENCE=0.35`：低于该置信度的 OCR 文本会被过滤。
- `ENABLE_VISION_OCR=false`：默认关闭 GPT 视觉 OCR。
- `OCR_CONCURRENCY=2`：保留给 OCR 并发控制，建议保持 1-3。
- `IMAGE_OCR_MAX_EDGE=1600`：图片 OCR 前自动压缩的最大边长。
- `IMAGE_OCR_JPEG_QUALITY=82`：图片 OCR 前转 JPEG 的质量。
- `BATCH_GENERATION_CONCURRENCY=3`：Brief 和正文批量生成的并发数，建议保持 1-8。
- `APP_DATA_DIR=app-data`：项目数据保存目录。

图片和扫描版 PDF 默认使用本地 OCR，不依赖中转站图片理解能力。

## 4. 安装依赖

第一次使用需要分别安装后端和前端依赖。

### 4.1 安装后端依赖

进入后端目录：

```bash
cd backend
```

创建 Python 虚拟环境：

```bash
python -m venv .venv
```

macOS / Linux 启用虚拟环境：

```bash
source .venv/bin/activate
```

Windows PowerShell 启用虚拟环境：

```powershell
.\.venv\Scripts\Activate.ps1
```

安装依赖：

```bash
pip install -r requirements.txt
```

### 4.2 安装前端依赖

新开一个终端，进入前端目录：

```bash
cd frontend
npm install
```

依赖只需要安装一次。以后启动项目不需要重复安装，除非项目代码更新。

## 5. 启动项目

本项目需要同时启动后端和前端，请打开两个终端窗口。

### 5.1 启动后端

终端 1：

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Windows PowerShell：

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

看到类似内容代表后端启动成功：

```text
Uvicorn running on http://127.0.0.1:8000
```

### 5.2 启动前端

终端 2：

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

看到类似内容代表前端启动成功：

```text
Local: http://127.0.0.1:5173/
```

### 5.3 打开网页

浏览器访问：

```text
http://127.0.0.1:5173
```

如果页面右上角能看到模型名和 Skill 状态，说明前后端连接正常。

## 6. 正确使用流程

建议严格按页面左侧流程操作。

### 第一步：创建或选择项目

在左侧项目区域：

1. 输入项目名称。
2. 点击创建项目。
3. 后续所有资料、输出、日志都会保存在该项目下。

建议项目名称使用客户或项目真实名称，例如：

```text
老板高端厨电 GEO 内容项目
```

### 第二步：上传资料

进入 `资料与信息` 页面。

按固定资料入口上传资料：

- 客户需求 brief。
- 核心关键词表。
- 品牌 / 产品资料。
- 核心证据资料。
- 竞品对比资料。
- 禁用词与合规边界。
- 可选补充资料。

支持格式：

```text
md, txt, json, csv, xlsx, pdf, jpg, jpeg, png, webp
```

上传建议：

- 文字资料优先使用 `md`、`txt`、`xlsx`、`csv`。
- PDF 如果是可复制文字的 PDF，系统会直接抽取文字。
- 扫描版 PDF 会尝试转图片并使用本地 OCR。
- 图片资料会尝试使用本地 OCR，不调用 GPT 视觉模型。
- 如果图片或 PDF OCR 不稳定，请补充一份文字版说明。

### 第三步：解析资料

资料上传后点击：

```text
解析资料
```

解析完成后，资料状态会显示 `parsed`。

如果某个文件解析失败：

- 检查格式是否支持。
- 检查文件是否损坏。
- 图片或扫描 PDF 失败时，检查中转站是否支持视觉模型。
- 可以补充文字版资料后重新解析。

已经解析成功的资料不会重复解析。

### 第四步：生成并确认项目信息

资料解析完成后，点击：

```text
生成抽取表
```

系统会自动生成 `项目信息自动抽取与确认` 表。

表格中每一行包含：

- 字段名。
- 推断值。
- 来源依据。
- 置信度。
- 当前状态。

运营人员需要逐行检查。

如果内容正确：

```text
点击该行的“确认”
```

如果内容需要调整：

```text
点击该行的“修改”
```

修改只编辑“推断值”。保存后会同步更新：

- 项目数据 `project.json`。
- 本地输出文件 `01-project-intake.md`。

全部确认后，点击：

```text
确认项目信息
```

### 第五步：生成内容矩阵

进入 `规划确认` 页面，点击：

```text
生成内容矩阵
```

系统会生成整体内容规划。

如果已经生成过，按钮会变成：

```text
重新生成内容矩阵
```

点击后会弹出二次确认。确认后会覆盖旧结果。

### 第六步：确认逐词击破关键词

内容矩阵生成后，在 `内容矩阵` Tab 中选择要进入逐词击破的关键词。

可以：

- 单个勾选。
- 全选。
- 清空选择。

选好后点击：

```text
确认关键词并进入逐词击破
```

### 第七步：生成逐词击破

切换到 `逐词击破` Tab，点击：

```text
生成逐词击破
```

系统会围绕已确认关键词生成固定六类文章规划：

- 支柱标准文。
- 榜单推荐文。
- 横评对比文。
- 场景选购文。
- 产品证据文。
- FAQ 问答文。

规划默认按关键词折叠显示。点击 `展开` 可以查看该关键词下的具体文章规划。

### 第八步：新增自定义文章

如果你想生成矩阵和逐词击破之外的文章，可以在 `规划确认` 页面使用：

```text
新增自定义文章
```

只需要输入文章标题。

系统会根据标题和项目上下文自动补齐关键词和文章类型。

如果某篇矩阵或逐词击破规划很接近你的想法，也可以点击：

```text
复制为自定义
```

然后修改标题。

### 第九步：选择规划并生成 Brief

在 `规划确认` 页面，勾选要生成 Brief 的文章规划。

可选来源包括：

- 内容矩阵规划。
- 逐词击破规划。
- 自定义文章。

勾选后点击：

```text
生成选中 Brief
```

系统只会为尚未生成 Brief 的选中项生成，已有 Brief 的项目会自动跳过，避免重复消耗额度。

### 第十步：审核和修改 Brief

进入 `Brief 审核` 页面。

你可以：

- 勾选 Brief。
- 查看 Brief。
- 修改 Brief Markdown。
- 保存修改。
- 重新生成单篇 Brief。

如果修改 Brief，系统会记录版本。已经生成过正文的文章会被标记为基于旧 Brief，需要重新生成正文。

确认 Brief 后，点击：

```text
确认 Brief
```

### 第十一步：选择 Brief 并生成正文

在 `Brief 审核` 页面勾选需要生成正文的 Brief，点击：

```text
生成选中正文
```

系统会跳转到 `正文审核` 页面。

正文生成后，你可以：

- 查阅正文。
- 修改正文 Markdown。
- 保存修改。
- 单篇重新生成。

### 第十二步：导出 Markdown

页面右上角点击：

```text
导出 Markdown
```

系统会下载一个 zip 文件，里面包含当前项目的 Markdown 输出。

本地输出文件也会保存在：

```text
app-data/projects/<项目ID>/outputs/
```

常见文件包括：

```text
01-project-intake.md
02-content-matrix.md
03-keyword-breakthrough.md
briefs/<source_id>-brief.md
articles/<brief_id>.md
```

## 7. 页面状态说明

常见状态含义：

- `pending`：还没有开始。
- `running`：后台正在运行。
- `completed`：已生成，等待确认。
- `confirmed`：已确认，可进入下一步。
- `failed`：失败，需要查看错误提示并重试。
- `parsed`：资料已解析。
- `ready_for_brief`：规划已准备好生成 Brief。
- `已人工修改`：项目信息由人工修改并保存。

如果页面显示 `running` 很久：

1. 点击右上角 `刷新状态`。
2. 查看页面提示或日志。
3. 如果后端窗口已经停止，重新启动后端。

## 8. 常见问题

### 8.1 页面打不开

检查前端是否启动：

```text
http://127.0.0.1:5173
```

如果打不开，回到前端终端重新运行：

```bash
npm run dev -- --host 127.0.0.1 --port 5173
```

### 8.2 页面能打开，但任务不能运行

检查后端是否启动：

```text
http://127.0.0.1:8000/api/agent/health
```

如果打不开，回到后端终端重新运行：

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 8.3 提示 API Key 或模型错误

检查 `.env`：

- `OPENAI_API_KEY` 是否填写。
- `OPENAI_BASE_URL` 是否以 `/v1` 结尾。
- `OPENAI_MODEL` 是否是中转站支持的模型名。
- `OPENAI_API_MODE` 是否为 `chat`。

修改 `.env` 后，需要重启后端。

### 8.4 图片或扫描 PDF 没有识别

检查：

- `ENABLE_LOCAL_OCR=true`。
- `LOCAL_OCR_ENGINE=rapidocr`。
- 是否已执行 `pip install -r backend/requirements.txt` 安装 `rapidocr-onnxruntime`。

如果本地 OCR 仍无法识别，请把图片中的内容整理成文字资料后上传。

### 8.5 点击生成后结果为空

先查看是否有错误提示。

常见原因：

- 资料不足。
- 项目信息未确认。
- 内容矩阵或逐词击破上一步未确认。
- 中转站返回格式异常。
- 模型没有按固定 JSON 模板输出。

可以尝试：

1. 补充资料。
2. 重新生成当前步骤。
3. 查看后台终端错误。
4. 导出 `project.json` 给技术同事排查。

### 8.6 重复点击生成会覆盖吗

规则如下：

- 内容矩阵已存在时，重新生成需要二次确认，会覆盖旧矩阵。
- Brief 和正文默认增量生成，已有内容会跳过，不会自动覆盖。
- 单篇 Brief 或正文可以在详情里重新生成。
- 自定义文章标题重复会被拒绝保存。

### 8.7 修改项目信息后会自动重跑规划吗

不会。

修改项目信息只会更新抽取表和 `01-project-intake.md`。如果希望后续规划使用新的信息，需要手动重新生成内容矩阵或后续步骤。

## 9. 数据备份

所有项目数据都在：

```text
app-data/
```

建议定期备份整个 `app-data/` 目录。

如果要把项目交给别人继续使用，可以把以下内容一起打包：

```text
app-data/projects/<项目ID>/
```

不要把 `.env` 发给无关人员，因为里面有 API Key。

## 10. 停止服务

后端和前端终端中按：

```text
Ctrl + C
```

即可停止服务。

下次使用时重新执行启动后端和启动前端命令即可。

## 11. 给技术同事的验证命令

如果需要检查项目是否正常，可运行：

```bash
cd backend
pytest
```

```bash
cd frontend
npm run build
```

两个命令都通过，说明后端逻辑和前端构建正常。
