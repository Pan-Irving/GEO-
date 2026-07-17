# GEO 撰文与发布工作台 macOS 运行包

这份包只包含运行所需代码、规则库、依赖清单、启动脚本和环境变量模板；不包含原机器上的 `app-data`、数据库、上传资料、缓存、虚拟环境、`node_modules` 或个人 `.env`。

## 1. 环境要求

- macOS
- Python 3.11 或更高版本
- Node.js 20 LTS 或更高版本
- npm

检查：

```bash
python3 --version
node --version
npm --version
```

## 2. 首次安装

在解压后的目录里执行：

```bash
chmod +x scripts/*.sh
./scripts/install-macos.sh
```

脚本会创建新的 Python 虚拟环境，并安装两个前端的 npm 依赖。

## 3. 配置 API Key

编辑根目录 `.env`，至少填写：

```env
OPENAI_API_KEY=你的写作模型_API_KEY
OPENAI_BASE_URL=https://你的中转站地址/v1
OPENAI_MODEL=你的模型名
OPENAI_API_MODE=chat
```

如需单独规划模型，再填写 `PLANNING_*`。不填 `PLANNING_API_KEY` 时，规划步骤会回退使用 `OPENAI_*`。

默认是本地文件存储，首次运行会在本机新建 `app-data/`，不会带入打包者的数据。

## 4. 启动

```bash
./scripts/start-all-macos.sh
```

访问：

- 撰文工作台：http://127.0.0.1:5173
- 发布工作台：http://127.0.0.1:5174

停止：在启动脚本所在终端按 `Ctrl+C`。

## 5. 常见问题

- 如果提示 `node_modules not found`，重新运行 `./scripts/install-macos.sh`。
- 如果提示虚拟环境不存在，重新运行 `./scripts/install-macos.sh`。
- 如果页面能打开但生成失败，检查 `.env` 里的 API Key、Base URL 和模型名。
- 如果要使用 MySQL，把 `.env` 中的 `WRITING_STORAGE_BACKEND`、`WRITING_DATABASE_URL`、`PUBLISHING_DATABASE_URL` 改成自己的数据库配置，并导入 `backend/sql/schema.mysql.sql` 和 `publishing/backend/sql/schema.mysql.sql`。
