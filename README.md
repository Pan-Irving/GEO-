# GEO 撰文后台 Agent

这个项目已经整理为本地 Python 后台 Agent + React 控制台。

## 结构

- `backend/`：FastAPI 后台 Agent，负责资料解析、读取 `mindsun-geo-content-flow` skill 规则、调用 OpenAI API、写入输出文件。
- `frontend/`：React 控制台，负责上传资料、启动分步任务、确认结果和导出文件。
- `mindsun-geo-content-flow/`：后台 Agent 使用的 skill 规则源。
- `app-data/`：运行时项目数据目录，自动生成，不提交。

## 后端启动

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
uvicorn app.main:app --reload
```

如果使用 LLM 中转站，在 `.env` 中配置：

```bash
OPENAI_API_KEY=你的中转站 key
OPENAI_BASE_URL=https://你的中转站地址/v1
OPENAI_MODEL=你的模型名
OPENAI_API_MODE=chat
OPENAI_VISION_MODEL=支持图片理解的模型名
ENABLE_VISION_OCR=true
VISION_OCR_MAX_PAGES=8
```

默认使用 Chat Completions 兼容模式，适配只支持 `/v1/chat/completions` 的中转站。如果你的服务支持 Responses API，可改为：

```bash
OPENAI_API_MODE=responses
```

图片资料会通过 `OPENAI_VISION_MODEL` 做 OCR/资料提取；如果不填，默认使用 `OPENAI_MODEL`。扫描版 PDF 在普通文本抽取失败时，会转成图片后再做 OCR。`VISION_OCR_MAX_PAGES` 用来限制扫描 PDF 最多 OCR 的页数，避免一次消耗过高。

## 前端启动

```bash
cd frontend
npm install
npm run dev
```

前端默认访问 `http://localhost:5173`，后端默认访问 `http://localhost:8000`。

## 测试

```bash
cd backend
pytest

cd ../frontend
npm run build
```

## 支持资料格式

首版支持 `md`、`txt`、`json`、`csv`、`xlsx`。Word/PDF 暂不解析。

## 工作流

后台 Agent 固定按以下步骤运行：

1. `materials`：上传资料
2. `intake`：项目信息自动抽取
3. `matrix`：内容矩阵规划
4. `breakthrough`：逐词击破规划
5. `brief`：Brief 生成
6. `article`：正文生成
7. `rewrite`：改写管理
8. `archive`：归档导出

除 `materials` 外，每一步完成后需要确认，才能进入下一步。
