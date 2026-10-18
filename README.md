# 个人知识 Agent（可运行 MVP）

这是一个本地优先、可自己修改代码的个人知识与事务 Agent。它不是演示页面：有 Python 后端、SQLite 数据库、Markdown 文件库、全文索引、响应式手机网页、独立后台邮箱轮询、邮件草稿和发送状态保护。

## 当前可以做什么

- **资料入库：** 粘贴文字，或上传 Markdown、TXT、PDF、HTML、CSV、JSON、XML 和常见图片。原始上传附件保存在 `vault/attachments/`，规范化文档写入 `vault/knowledge/`。
- **检索与引用：** SQLite FTS5 全文索引 + 子串回退检索；问答返回检索来源、文档 ID 和 Markdown 路径，可打开原文。
- **文件外部编辑：** 你可以直接编辑 `vault/knowledge/` 或 `vault/rules/` 中的 Markdown。后台会定期同步索引；在网页保存后立即更新。新增的普通 Markdown 文件也会获得稳定 ID 元数据。
- **长期规则：** 在网页中保存纠正，例如“必须区分活动开始时间和报名截止时间”。规则写入 `vault/rules/*.md`，会在后续知识问答与邮件拟稿中被读取。
- **邮箱：** 通过 IMAP 读取邮件，通过 `Message-ID / In-Reply-To / References` 尽可能关联线程，并把近期历史往来带入新邮件回复草稿。每封新邮件有唯一数据库记录，定时轮询不会重复创建草稿。
- **人工确认发送：** 只有你在网页编辑并点击“确认并发送此版本”，然后在确认框中确认收件人、主题和完整正文，系统才会调用 SMTP。已发送草稿会阻止重复发送；遇到 SMTP 超时等结果不确定情况会锁定草稿，不会自动重试。
- **手机端：** 响应式网页/PWA 样式，可在手机浏览器使用；不依赖桌面端对话窗口常驻。后台任务依赖运行此项目的服务进程持续运行，而不依赖网页保持打开。
- **Git：** 源码、文档、提示词和规则模板适合纳入 Git。`.env`、数据库、私人笔记附件默认忽略。

## 1. Windows 本地启动（推荐先这样验证）

1. 安装 Python 3.11 或更新版本，并确保安装时启用了 `py` 启动器（或者可以从终端执行 `python`）。
2. 解压项目文件夹。
3. 双击 `start.bat`。脚本会创建 `.venv`、安装依赖、第一次运行时复制 `.env.example` 为 `.env`，然后启动服务。
4. 浏览器打开 `http://127.0.0.1:8000`。

首次启动不要求 AI 密钥或邮箱账号。未配置模型时，资料管理、Markdown 编辑、规则保存和关键词检索仍可运行；问答会明确提示模型未配置，不会把检索结果伪装成 AI 综合回答。

也可以手动运行：

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 2. macOS / Linux 启动

```bash
chmod +x start.sh
./start.sh
```

或者手动执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

停止服务时，在运行服务的终端按 `Ctrl+C`。资料文件与数据库保留在 `vault/` 和 `data/` 中。

## 3. 配置 AI 模型（可选，但问答/摘要/拟稿需要）

编辑 `.env`：

```dotenv
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=你的_API_密钥
LLM_MODEL=你有权限调用的模型名称
```

程序使用 OpenAI-compatible Chat Completions 接口。模型供应商会接收发送给该接口的查询、检索到的文档片段或邮件内容；请在使用敏感资料前确认服务条款与数据处理政策。没有模型密钥时，项目不会向外部模型服务发送内容。修改 `.env` 后请重启服务。

如果你使用本机运行的 Ollama 或其他 OpenAI-compatible 本地模型，可以把 `LLM_BASE_URL` 指向本地端点并设置模型名，例如：

```dotenv
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_API_KEY=
LLM_MODEL=你本机已安装的模型名
```

本地无认证模型仅允许使用 localhost / loopback 或指定的本地服务主机名；容器中访问宿主机时通常需要 `host.docker.internal`，并确认模型服务已允许该访问方式。

图片文字提取需要支持视觉输入的模型。扫描版 PDF 当前不会自动 OCR；原文件仍会保存，文本提取为空时界面应提示需要人工检查或后续接入 OCR。

## 4. 配置邮箱（可选）

你的邮箱服务必须允许 IMAP/SMTP 访问。不同服务商的服务器地址、端口和授权方式不同，请使用该服务商自己的设置；优先使用应用专用密码或 OAuth，不要把主账号密码写入代码。

在 `.env` 设置对应值：

```dotenv
MAIL_ACCOUNT=main
IMAP_HOST=imap.example.com
IMAP_PORT=993
IMAP_USER=你的邮箱地址
IMAP_PASSWORD=应用专用密码
IMAP_FOLDER=INBOX
IMAP_POLL_SECONDS=120
IMAP_INITIAL_BACKFILL=80

SMTP_HOST=smtp.example.com
SMTP_PORT=465
SMTP_USER=你的邮箱地址
SMTP_PASSWORD=应用专用密码
SMTP_USE_SSL=true
SMTP_STARTTLS=false
MAIL_FROM=你的邮箱地址
```

对于使用 STARTTLS 的服务，可配置其指定的端口，例如 `SMTP_PORT=587`、`SMTP_USE_SSL=false`、`SMTP_STARTTLS=true`。不要猜服务器地址；以你的邮箱服务商文档为准。保存 `.env` 后请重启服务，后台会在启动后读取新配置。

### 首次邮箱同步的安全行为

第一次连接或邮箱 UID 标识被重置时，Agent 最多把最近 `IMAP_INITIAL_BACKFILL` 封邮件导入为历史上下文，**不会为这些旧邮件自动创建回复草稿**。之后只会对新增 UID 的邮件创建草稿。将 `IMAP_INITIAL_BACKFILL=0` 可以跳过历史导入。

草稿如果显示 `SEND_UNCERTAIN`，表示 SMTP 响应不确定或服务在发送中途重启。Agent 为避免重复发送会阻止自动重试；请先在邮箱“已发送”中核对，再人工处理该草稿。不要因为出现网络错误就盲目重发。

## 5. 手机端使用

默认只监听 `127.0.0.1`，这是有意的安全默认值：项目不需要密码也不会直接暴露给局域网或互联网。

若要在同一可信 Wi-Fi 下由手机访问：

1. 在 `.env` 设置一个独立强密码，例如 `APP_PASSWORD=一段长且随机的密码`。
2. 将 `HOST=127.0.0.1` 改为 `HOST=0.0.0.0`，重启服务。
3. 在电脑上找到局域网 IPv4 地址（Windows 可运行 `ipconfig`），手机与电脑连接同一网络，然后打开 `http://电脑局域网IP:8000` 并输入密码。
4. 仅在可信网络中使用 HTTP。跨网络访问请优先用 Tailscale/其他私有 VPN；公网部署必须添加 HTTPS 反向代理、防火墙和强身份认证。不要把裸 HTTP 服务直接暴露到公网。

PWA 可安装能力取决于浏览器及 HTTPS 要求；即使没有安装选项，手机浏览器仍可访问响应式界面。网页关闭后，后台同步在服务进程继续运行时照常进行。

## 6. 数据与目录

```text
app/
  main.py                 FastAPI API、后台任务与鉴权
  db.py                   SQLite schema、任务状态与日志
  knowledge.py            Markdown 入库、解析、FTS 索引、规则和引用
  model.py                可选模型接口、摘要与图片文本抽取
  mail_service.py         IMAP、线程关联、草稿、SMTP 防重发送
  static/                 手机友好前端 / PWA
vault/
  knowledge/              可阅读、可修改的个人资料 Markdown
  rules/                  长期纠正规则 Markdown
  topics/                 可直接放入的主题笔记
  attachments/            上传文件原件（可能含私人信息）
data/
  agent.sqlite3           全文索引、邮件去重状态、草稿、任务状态和日志
.env                      私人配置和密码（不会纳入 Git）
```

## 7. Git 管理

本交付包包含已初始化的本地 Git 仓库和初始提交。进入项目目录后可以查看历史：

```bash
git log --oneline
git status
```

每次新增长期规则、调整检索逻辑或修复错误后，检查 `git status`、`git diff` 和测试结果再提交：

```bash
python -m pytest -q
git add app tests README.md requirements.txt .env.example .gitignore vault/rules docs
git commit -m "Describe the change"
```

`vault/rules/` 默认可被 Git 跟踪，让纠正规则有明确的版本历史；`vault/knowledge/`、`vault/attachments/` 和 `vault/topics/` 中的私人资料默认被忽略，以免把个人内容意外推送到远程仓库。`.env` 和数据库也默认忽略。提交规则前仍应检查是否包含个人或敏感信息。此版本使用本地 Git，不需要绑定任何远程仓库。

## 8. 验证与测试

```bash
python -m pytest -q
```

运行后端 API 可查看：

- 健康检查：`http://127.0.0.1:8000/api/health`
- OpenAPI 文档：`http://127.0.0.1:8000/docs`（如果设置了 `APP_PASSWORD`，API 请求需要认证）

## 当前 MVP 边界

- 使用 SQLite FTS5，不依赖外部向量数据库；资料量非常大后可以再加语义向量检索。
- 通用 IMAP/SMTP 是适配层，不代表任意邮箱服务都允许密码登录或 SMTP 发送。
- 未内置 OCR；扫描件提取需人工检查或接 OCR 服务。
- 用户访问是单用户轻量认证，适合个人自托管；不应作为多租户 SaaS 直接公开部署。
- 没有任何系统能在所有 SMTP 超时场景中数学上保证 exactly-once；本项目采取“数据库幂等状态 + 不确定时锁定、不自动重试”的保守策略，降低重复发送风险。
