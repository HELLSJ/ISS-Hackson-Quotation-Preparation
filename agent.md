# Project handoff — Quotation Preparation Agent

## 项目目标

NUS-ISS Hackathon 选题 **Quotation Preparation**。在 10 天内完成一个报价 Agent：读取不完整的英文客户询价，主动追问缺失条件，从有证据的产品目录筛选型号，用确定性工具计价，经用户确认后保存报价版本并导出 PDF。

主线流程：

```text
询价 → 提取需求 → 追问 → 搜索产品 → 展示证据 → 用户确认
     → 工具计价 → 保存 v1/v2 → 显示 diff → 导出 PDF
```

## 当前状态（2026-09-15）

数据、离线 Agent、FastAPI、SQLite 报价快照和三栏浏览器工作台已经打通；真实 Bedrock 调用、报价 PDF 和版本 diff 尚未完成。

- 6 份 Dell 官方英文 PDF，共 522 页；
- 12 个显示器型号、12 条模拟 SGD 价格；
- 96 条字段级证据，可从页面打开 PDF 对应页；
- 20 条 dev、20 条 holdout、3 条视频演示案例；
- `tests/` 15 项通过，`dell_agent/tests/` 63 项通过、7 项明确 skip；
- 三条固定演示均可离线运行，包括 U2724D data-only 陷阱；
- `app/` 支持对话恢复、候选选择、确定性计价和幂等保存 v1/v2；
- 数据版本：`2026-09-14.v1`；
- 尚未使用团队 AWS 账户调用模型；不能声称模型评估已通过；
- 还需队员独立抽查 6 个型号，每个核对 2 个字段，然后冻结数据。

不需要继续下载产品、实时价格、库存或客户数据。规格来自官方资料；价格、规则和询价均为比赛用模拟数据。

## 先读这些文件

1. `docs/project-plan-zh.md`：唯一项目总规划，包含当前进展、剩余 Gate、分工、验收指标和视频结构；
2. `README.md` / `README.zh-CN.md`：英文仓库入口和中文说明；
3. `data/README.md`：数据字段、来源、运行方法和可信范围；
4. `docs/api-contract.md`：冻结的工具和 HTTP 契约；
5. `data/agent/catalog.json`：Agent/后端运行时数据；
6. `data/agent/bedrock_tool_config.json`：Bedrock Converse 工具定义；
7. `data/evaluation/demo_scenarios.jsonl`：三条固定演示故事。

## 已有工具

`dell_agent.agent.tools.dispatch` 提供三个冻结工具，`scripts/catalog_tools.py` 只是一层 CLI 包装：

- `search_products`：结构化产品筛选；
- `get_product`：读取 SKU、模拟价格和字段证据；
- `calculate_quote`：使用服务器价格与固定规则计算草稿。

不要让模型或前端生成单价、计算金额或覆盖工具价格。金额使用整数分，折扣上限为 500 bps（5%），舍入为 half-up。库存、交期和税费没有数据，必须显示为未知或转人工确认。

常用命令：

```bash
python scripts/validate_data.py
python -m unittest discover -s tests -v
python scripts/catalog_tools.py search_products '{"usb_c_video":true,"min_pd_watts":90}'
python scripts/catalog_tools.py calculate_quote '{"items":[{"sku":"MON-007","quantity":8}],"budget_cents":250000}'
```

## 推荐实现

```text
Browser workbench (`app/static/`)
  → FastAPI (`app/main.py`)
      → QuotationService：有序轮次重放、回复与替代建议
      → OfflineDriver / Amazon Bedrock Converse
      → dell_agent.agent.tools.dispatch（唯一查事实和计价实现）
      → SQLite `storage/app.sqlite`（消息和不可变报价版本）
      → 本地官方 PDF 证据页
```

本地运行：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000`。Bedrock 配置见根 `README.md`；没有配置时使用确定性 OfflineDriver。

## 三条固定演示故事

1. **模糊询价：** 8 台 USB-C 显示器、预算 SGD 2,500。追问视频和供电后选 P2425HE；8 台为 SGD 2,312。改为 10 台生成 v2，SGD 2,890，超预算 SGD 390。
2. **规格陷阱：** U2724D 有 USB-C data-only，不能满足一线视频和 90 W 供电；用户同意后才可推荐 U2724DE。
3. **政策边界：** 5 台 S2725QC、6% 折扣、承诺明日交付。必须拒绝超出 5% 的折扣，并把交期标为待确认，不得显示为已批准。

## 四人主责

- A：数据与评估；
- B：FastAPI、报价后端、版本和 PDF；
- C：AWS Bedrock Agent、状态机和失败回退；
- D：前端、证据交互、视频和提交。

Day 1 冻结 API 契约，之后四人并行；每天用第一条演示故事做一次端到端集成。Day 8 功能冻结，Day 9 彩排，Day 10 录制和提交。

## 下一步

1. 用团队 AWS 账户完成一次真实 Bedrock Converse 工具调用，确认未走 fallback；
2. 完成数据人工抽查并冻结 `2026-09-14.v1`；
3. 基于 `quote_versions.payload_json` 实现 v1/v2 diff 和 PDF；
4. 运行 holdout 首轮评估并保留失败项；
5. 每天用三条演示故事做端到端回归。

继续开发时先检查实际文件和测试结果，不要重新下载或重建已经完成的数据，也不要把 holdout 案例放入提示词或知识库。
