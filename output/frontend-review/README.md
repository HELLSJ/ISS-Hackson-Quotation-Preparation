# Frontend workspace review — 2026-09-24

本次仅修改 `app/static/index.html`、`app/static/styles.css` 和 `app/static/app.js`。

## 页面变化

- 桌面为左侧对话、右侧工作区，选产品和看报价可以切换。
- 新的报价结果自动进入报价页；切换页签不发起后台写入。
- 场景入口在开始询价后收起；完整目录、工具日志和旧版本按需展开。
- 没有匹配结果时不会把完整目录冒充候选结果。
- 当前草稿总额固定显示，超预算及其他冲突明确提示。
- 证据以右侧抽屉呈现；最新版本保持展开，旧版本折叠。
- 版本差异使用 SGD 金额和百分比展示。
- 产品卡片仍沿用原有“一台、零折扣”的请求，按钮明确标为 Quote 1 unit。本次未改变数量解析、计价、保存、确认或导出逻辑。

## 实际截图

- `01-start.jpeg`：首页与折叠目录。
- `02-confirmed-quote.jpeg`：报价工作区，总额固定显示。
- `03-evidence-drawer.jpeg`：厂商证据抽屉。

截图来自本地 Microsoft Edge 实际页面，使用 offline 模式；不是设计稿。

## 验证

- `node --check app/static/app.js` 和 `git diff --check` 通过。
- 现有 tests 测试集：77/77 通过。环境缺少 httpx2 和 pypdf，验证依赖装在 `/tmp/quotation-ui-test-deps`，没有修改项目依赖文件或 .venv。
- 浏览器实测：询价澄清、候选显示、自动切换报价、8 台 SGD 2,312、修订 10 台 SGD 2,890、超预算 SGD 390、保存 v1/v2、版本比较、确认和 PDF 下载。
- 检查证据抽屉、双向页签切换及 125% 浏览器缩放。
- 移动端有响应式样式，本次没有进行手机实机验收。
- 验收服务使用 `/tmp/quotation-ui-review.sqlite`，未使用业务数据库保存演示记录。

## 启动

在项目目录运行：

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000 。默认 offline 模式不需要密钥；已有 Gateway 环境配置继续按原方式生效。

若尚未安装环境：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

当前本地预览使用 offline 模式和临时数据库。若 8000 正在使用，可用 `--port 8001` 启动另一个实例并打开 http://127.0.0.1:8001 。

页面刷新仍按原设计创建新询价，历史快照保存在服务端；本次未改动会话恢复行为。公网演示未部署更新。
