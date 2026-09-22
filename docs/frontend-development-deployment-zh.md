# 前端开发、验收与部署指南

本文面向负责前端优化的团队成员，说明现有页面结构、允许修改的范围、API 对接方式、验收要求，以及如何把改动发布到 AWS Lightsail。

## 1. 当前架构

前端是由 FastAPI 直接托管的原生 HTML、CSS 和 JavaScript，没有 React、Vue、Node.js 或打包步骤。

```text
浏览器
  → app/static/index.html
  → app/static/styles.css
  → app/static/app.js
  → 同源 /api/*
  → FastAPI、SQLite、GatewayDriver 和确定性报价工具
```

生产环境由 Nginx 接收公网 80/443 请求，再转发到服务器内部的 `127.0.0.1:8000`。日常前端更新不需要修改 Nginx。

## 2. 前端文件

| 文件 | 职责 | 常见修改 |
|---|---|---|
| `app/static/index.html` | 页面语义结构和固定文案 | 面板结构、按钮、dialog、辅助说明 |
| `app/static/styles.css` | 视觉系统和响应式布局 | 颜色、间距、字体、桌面/移动布局、状态样式 |
| `app/static/app.js` | 页面状态、API 调用和渲染 | 对话、候选、证据、报价版本、diff、确认、下载 |
| `app/main.py` | HTTP 路由 | 只在确实需要新 API 时由后端负责人修改 |
| `docs/api-contract.md` | 冻结的 API 与业务契约 | API 变化必须同步更新 |

主要 JavaScript 渲染入口：

| 函数 | 对应页面区域 |
|---|---|
| `boot()` | 加载健康状态、目录和历史会话 |
| `renderStatus()` | Gateway/fallback 与业务状态徽章 |
| `renderMessages()` | 客户与 Agent 消息 |
| `renderRequirements()` | 尚缺需求字段 |
| `renderCandidates()` | 产品候选和兼容性提示 |
| `renderTrace()` | 可展开的工具审计 |
| `renderQuote()` | 未确认报价草稿 |
| `renderVersions()` | 保存、确认、diff 和 PDF 操作 |

## 3. 不能破坏的业务边界

### 3.1 前端不能重新计算事实或金额

前端只能格式化后端返回的整数分：

```javascript
money(total_cents)
```

不要在 JavaScript 中重新计算单价、折扣、行金额、总额或预算差额。不要在页面内硬编码 SKU 事实、价格和折扣上限。

### 3.2 保留报价生命周期

```text
draft → saved_draft → confirmed/exportable
```

- `draft` 只是当前计算结果；
- `saved_draft` 是不可变版本，但尚未批准；
- 只有 `confirmed` schema-v2 快照可以下载 PDF；
- 前端必须使用后端提供的 `result_message_id` 和 `snapshot_token`；
- 收到 409 时显示错误并刷新数据，不能绕过 stale 检查。

### 3.3 未知信息必须继续显示为未知

库存、交付时间和税费没有数据。前端不能把 `null` 显示成“有货”“明日送达”或“含税”。

### 3.4 保留安全输出

- 所有普通文本进入 HTML 前使用 `escapeHtml()`；
- Markdown 渲染只接受当前受控子集；
- 链接只允许 `https://` 或后端生成的同源路径；
- 外部新窗口链接保留 `rel="noopener"`；
- 不在页面、日志、截图或提交中加入 Gateway API key；
- 不通过前端读取 `.env`，密钥只存在服务器进程环境中。

## 4. 当前 HTTP API

完整契约见 [API 与工具契约](api-contract.md)。常用端点如下：

| 功能 | 请求 |
|---|---|
| 健康状态 | `GET /api/health` |
| 产品列表 | `GET /api/products` |
| 产品与证据 | `GET /api/products/{sku}` |
| 创建会话 | `POST /api/conversations` |
| 恢复会话 | `GET /api/conversations/{id}` |
| 发送询价 | `POST /api/conversations/{id}/messages` |
| 修改数量/直接计价 | `POST /api/quotes/calculate` |
| 保存当前草稿 | `POST /api/conversations/{id}/quotes` |
| 读取报价版本 | `GET /api/quotes/{id}` |
| 确认报价版本 | `POST /api/quotes/{id}/confirm` |
| 比较两个版本 | `GET /api/quotes/{from}/diff/{to}` |
| 下载已确认 PDF | `GET /api/quotes/{id}/pdf` |

统一错误格式：

```json
{
  "detail": {
    "error": "stale_draft",
    "message": "The displayed draft is no longer the latest result."
  }
}
```

页面应向用户显示 `detail.message`，不要只显示 HTTP 状态码。

## 5. 本地开发

### 5.1 取得最新代码

建议在独立前端分支工作：

```bash
git fetch origin
git switch -c feat/frontend-polish origin/chore/readme-and-data-pipeline
```

如果已经存在该分支：

```bash
git switch feat/frontend-polish
git pull --ff-only
```

### 5.2 创建环境

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/build_data.py
```

使用 OfflineDriver 做纯界面开发不需要云配置：

```bash
AGENT_DRIVER=offline .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

需要验证真实 Gateway 时，可使用本地、已被 `.gitignore` 忽略的 `.env`：

```bash
set -a
source .env
set +a
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开：

```text
http://127.0.0.1:8000/
http://127.0.0.1:8000/docs
```

不要提交 `.env`，也不要在测试截图中露出密钥。

## 6. 推荐的优化范围

前端可以独立完成：

- 改善桌面、平板和手机布局；
- 优化字体、间距、按钮层级和状态反馈；
- 增加 loading、disabled、empty 和 error 状态的可读性；
- 改善候选卡、工具审计、报价版本和 diff 的信息层级；
- 改善 dialog 的键盘操作、焦点和关闭行为；
- 增加无障碍名称、焦点样式和颜色对比度；
- 在不改变 API 语义的前提下重构渲染函数。

需要先与后端负责人同步：

- 新增或修改 API；
- 修改请求或响应字段；
- 修改保存、确认、diff 或 PDF 流程；
- 在浏览器中新增任何金额计算；
- 修改 Gateway prompt、产品事实或定价规则。

## 7. 浏览器验收

每次前端改动至少检查以下流程。

### Story A：澄清、报价与修订

```text
We need 8 monitors with USB-C. Budget SGD 2500.
Video plus at least 65W charging; 23.8-inch FHD is acceptable.
Choose P2425HE at zero discount.
```

验收：

- 草稿为 SGD 2,312.00；
- 保存 v1；
- 把数量改为 10 后草稿为 SGD 2,890.00；
- 显示超预算 SGD 390.00；
- 保存 v2 并显示 v1 → v2 diff；
- 确认后才出现 PDF 下载。

### Story B：端口能力边界

```text
Quote 4 U2724D for one-cable laptop video and 90W charging.
```

验收：显示 U2724D 的 data-only 限制和来源证据；可以建议 U2724DE，但不能自动替换或生成报价。

### Story C：政策边界

```text
Quote 5 S2725QC with a 6% discount and guarantee delivery tomorrow.
```

验收：显示 5% 折扣上限和交付未知，不生成计算行；工具审计可以展开查看。

### 响应式和交互

- 1440px：三栏完整显示；
- 768–1100px：两栏加独立报价区；
- 小于 720px：单栏，无横向页面溢出；
- 键盘可操作发送、证据、确认和 dialog；
- 刷新后恢复 conversation；
- `Reset demo` 创建干净会话；
- Gateway fallback 必须明确显示为 `Offline fallback`。

## 8. 自动检查

提交前运行：

```bash
node --check app/static/app.js
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m unittest discover -s dell_agent/tests
git diff --check
```

纯 CSS/文案修改不需要新增测试。修改保存、确认、diff、API 错误处理或状态映射时，应补充有业务价值的测试。

## 9. 缓存版本

`index.html` 当前用查询参数让浏览器获取最新版静态文件：

```html
<link rel="stylesheet" href="/static/styles.css?v=20260922-2">
<script src="/static/app.js?v=20260922-2" defer></script>
```

修改 CSS 或 JavaScript 并准备部署时，同时递增两个版本，例如：

```html
/static/styles.css?v=20260923-1
/static/app.js?v=20260923-1
```

不要只改其中一个。部署后使用强制刷新验证。

## 10. Git 协作

```bash
git status --short
git add app/static docs/frontend-development-deployment-zh.md
git commit -m "feat: polish quotation workbench UI"
git push -u origin feat/frontend-polish
```

合并前提供：

- 桌面和移动截图；
- Story A/B/C 验收结果；
- 自动检查结果；
- 是否改动 API、状态映射或缓存版本；
- 已知限制。

不要提交 `storage/`、`.env`、虚拟环境、浏览器日志或真实客户信息。

## 11. 发布到 Lightsail

前端分支合并到服务器当前部署分支后，SSH 登录 Lightsail：

```bash
cd /home/ubuntu/ISS-Hackson-Quotation-Preparation
git status --short
git branch --show-current
git pull --ff-only origin chore/readme-and-data-pipeline
sudo systemctl restart quotation-agent
sudo systemctl status quotation-agent --no-pager
```

如果 `requirements.txt` 有变化，再执行：

```bash
.venv/bin/pip install -r requirements.txt
sudo systemctl restart quotation-agent
```

服务器检查：

```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1/api/health
sudo journalctl -u quotation-agent -n 100 --no-pager
```

公网检查：

```text
http://<PUBLIC_IP_OR_DOMAIN>/
http://<PUBLIC_IP_OR_DOMAIN>/api/health
```

Nginx 会继续转发请求，不需要为普通前端更新重新配置。不要直接在服务器上编辑 `app/static/`，否则下一次 `git pull` 容易产生冲突。

## 12. 完成标准

一项前端优化只有同时满足以下条件才算完成：

- 页面在桌面和手机宽度下可用；
- Story A/B/C 的状态、金额和阻断行为没有变化；
- 保存、确认、diff 和 PDF 生命周期完整；
- 所有用户输入和模型文本安全转义；
- 页面不暴露密钥、Gateway URL 或服务器环境；
- JavaScript 语法、相关测试和 `git diff --check` 通过；
- 静态资源缓存版本已更新；
- Lightsail 公网页面完成一次实际验证。
