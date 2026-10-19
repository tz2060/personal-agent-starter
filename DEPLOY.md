# 部署与远程访问

本项目是 **有状态** 的：`data/agent.sqlite3`（索引、邮件去重状态、草稿）和 `vault/`（Markdown 资料、附件）是运行数据，不是可以随时重建的缓存。同时后台 IMAP 轮询依赖服务进程持续运行。

因此它**不能**部署到 GitHub Pages —— Pages 只托管静态文件，没有 Python 运行时、没有可写磁盘、也没有常驻进程。GitHub 在这里只承担代码托管，运行需要另找一台机器。

## 一、推送到 GitHub

首次推送前先设置提交身份（默认的占位身份不会关联到你的 GitHub 账号）：

```bash
git config user.name "你的名字"
git config user.email "你的GitHub邮箱"
```

在 GitHub 网页新建**空仓库**（不要勾选 README、.gitignore、License），然后：

```bash
git remote add origin https://github.com/<用户名>/<仓库名>.git
git branch -M main
git push -u origin main
```

HTTPS 推送要求 Personal Access Token 而非账号密码：GitHub → Settings → Developer settings → Personal access tokens → 生成时勾选 `repo`。

### 推送前确认没有私人数据

`.gitignore` 已排除 `.env`、`data/*`、`vault/knowledge/*`、`vault/attachments/*`、`vault/topics/*`、`.venv/`。提交前仍建议自查：

```bash
git ls-files | grep -Ei "\.env$|sqlite|\.venv"   # 应无输出
```

`vault/rules/` 是**会被跟踪**的（规则需要版本历史），提交前确认里面没有个人隐私。

## 二、选择运行方式

| 方案 | 免费 | 7×24 运行 | 数据持久 | 代价 |
|---|---|---|---|---|
| 笔记本本地 + 同 Wi-Fi 访问 | ✅ | ❌ | ✅ | 需在同一网络 |
| 笔记本本地 + Tailscale / ZeroTier | ✅ | ❌ | ✅ | 笔记本需开机 |
| GitHub Codespaces | ✅ 120 核时/月 | ❌ 30 分钟空闲自停 | ✅ | 非常驻 |
| VPS + Docker Compose | ❌ 约 ¥20–40/月 | ✅ | ✅ | 需自行运维 |

**不要用 Render / Railway 免费层**：免费实例是临时磁盘，重启后数据库和 vault 全部丢失；且免费 Web 服务在无请求约 15 分钟后休眠，IMAP 轮询会中断。

## 三、笔记本本地运行

1. 编辑 `.env`：
   - `HOST=0.0.0.0`（允许其他设备访问；仅本机用则保持 `127.0.0.1`）
   - `APP_PASSWORD`：**建议**设为一串长随机密码
2. 双击 `start.bat`。
3. 启动后终端会直接打印两个可用地址（本机 + 局域网），照着点开即可；网页「运行状态 → 手机 / 其他设备访问地址」里也有同样的信息。设了 `APP_PASSWORD` 时首次需输入密码。

> 终端里不会再出现 `http://0.0.0.0:8000` 这种提示——那是 uvicorn 打印的**绑定地址**，浏览器打不开。应用已在启动时把它过滤掉并替换为真实地址。

### 关于免密码运行

本项目原始设计会在 `HOST=0.0.0.0` 且 `APP_PASSWORD` 为空时**拒绝启动**。当前仓库已把这道拒绝改为启动日志中的 `SECURITY` 警告，以支持局域网免密码使用。

免密码意味着同一网络内**任何设备**都能：读取 `vault/` 全部资料、浏览邮件正文、创建与编辑回复草稿。发送仍需在页面上人工确认，但资料与邮件内容是裸奔的。因此：

- 只在可信网络（家庭 Wi-Fi、手机热点）中使用。
- **绝对不要**把无密码实例映射到公网，也不要在这类网络（咖啡馆、酒店、公司访客 Wi-Fi）里开。
- 想恢复保护：在 `.env` 填回 `APP_PASSWORD` 并重启即可，无需改代码。

鉴权说明：密码本身即 Bearer token（`POST /api/login` 换取），单用户轻量认证，不要用于多租户场景。`/api/health` 是有意公开的状态接口，不含密钥或正文内容。

## 四、手机访问

### 方案 A：同一 Wi-Fi（最简单，不装任何工具）

网页「总览 → 运行状态 → 本机访问地址」会显示可用的局域网地址，手机照抄即可。若那里为空，用命令行核对：

在电脑上查局域网地址：

```powershell
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike "127.*" }
```

手机连同一 Wi-Fi，浏览器打开 `http://<电脑IP>:8000`，输入 `APP_PASSWORD`。首次启动时 Windows 防火墙会弹窗，需允许「专用网络」。

### 方案 B：跨网络（Tailscale / ZeroTier）

1. 电脑和手机分别安装 Tailscale，登录**同一账号**。
2. 电脑上取 Tailscale 地址：`tailscale ip -4`（形如 `100.x.x.x`）。
3. 手机访问 `http://100.x.x.x:8000`。

可选 HTTPS：`tailscale serve --bg 8000` 会分配一个 `https://<机器名>.<tailnet>.ts.net` 域名，装了证书后 PWA 才能"添加到主屏幕"。

> **国内可用性提示**：Tailscale 的协调服务器与 DERP 中继在部分网络下连接不稳定。若无法登录或设备互相 ping 不通，改用 **ZeroTier**（同为免费，国内成功率更高），或直接使用方案 A。

## 五、让后台轮询持续工作

邮件轮询跑在服务进程里，进程一停就不再收信，与网页是否打开无关。

- **合盖不休眠**：控制面板 → 电源选项 → 选择关闭盖子的功能 → 「接通电源时：不采取任何操作」。（仅电池时建议保留休眠，避免放包里过热。）
- **开机自启**：`Win+R` 输入 `shell:startup`，把 `start.bat` 的快捷方式放进去。
- **服务化（更稳）**：用 `nssm install` 把 uvicorn 注册成 Windows 服务，崩溃自动拉起。

## 六、日常更新流程

```bash
python -m pytest -q
git add -A
git commit -m "描述改动"
git push
```

拉取到另一台机器后只需重启服务；数据库和 vault 不随代码同步。

## 七、把单篇资料发布到 GitHub

资料库页面每篇资料右侧有「发布」按钮，把这**一个** Markdown 文件推到 GitHub 仓库的指定目录。

在 `.env` 配置：

```dotenv
GITHUB_TOKEN=github_pat_xxxxxxxx
GITHUB_REPO=owner/repo
GITHUB_BRANCH=main
GITHUB_NOTES_DIR=notes
```

- `GITHUB_TOKEN`：Fine-grained token，对目标仓库授予 **Contents: Read and write** 即可，不必给全仓库权限。
- `GITHUB_REPO`：`owner/repo` 格式。
- 文件写到 `{GITHUB_NOTES_DIR}/{原文件名}.md`，例如 `notes/basal-ganglia--876d8c.md`。
- 同一篇再次发布会覆盖原文件并生成新提交（自动带 `sha`），不会产生重复文件。
- `GITHUB_TOKEN` 或 `GITHUB_REPO` 留空时，按钮不显示。

实现走 **GitHub Contents API** 而不是 git 命令，原因有两个：服务进程里拿不到本机 git 凭据助手（GCM 会弹窗等交互）；而且 `vault/knowledge/` 在 `.gitignore` 里，走 git 需要 `-f` 强制添加，容易连带提交整批私人文件。单篇、显式、可回退，更安全。

> **⚠️ 公开仓库 = 公开发布。** 若 `GITHUB_REPO` 指向公开仓库，笔记内容对所有人可见。私人资料请另建一个 **private** 仓库，并让 token 只授权那一个仓库。

## 八、安全红线

- `.env` 含 LLM 密钥、IMAP/SMTP 授权码、访问密码，**永远不要提交**。
- **当前实例以无密码方式在局域网运行**，同网段任何设备均可读取资料与邮件。不要在不可信网络（公共 Wi-Fi、访客网络）中启动。
- 公网暴露必须加 HTTPS 反向代理 + 防火墙 + 强密码；不要直接把裸 HTTP 服务开到公网。
- 优先使用邮箱的「应用专用密码」，不要用主账号密码。
- 后台任务会读取邮件正文并可能发送给模型服务商，使用敏感资料前先确认其数据处理政策。
