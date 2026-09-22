# Quotation Preparation Agent — 简要交接

## 项目信息

NUS-ISS Hackathon 报价编制 Agent：把不完整的英文客户询价经过澄清、产品筛选、证据核对和确定性计价，转成可保存、可修改、最终可导出的报价。

```text
询价 → 追问 → 查询产品 → 展示证据 → 用户选择
→ 工具计价 → 保存版本 → 版本 diff → 确认 → PDF
```

核心原则：**模型负责理解和追问；`dell_agent.agent.tools.dispatch` 负责所有产品事实、价格、规则和金额。** 产品规格来自 Dell 官方手册；价格、规则和询价均为模拟数据。库存、交期和税费未知，不能推断。

## 已完成

- 6 份 Dell 官方手册、12 个显示器 SKU、12 条模拟 SGD 价格和 96 条字段证据；
- `search_products`、`get_product`、`calculate_quote` 三个统一工具；
- OfflineDriver：支持澄清、限制说明、规则阻断、计价和多轮修改；
- FastAPI、`storage/app.sqlite` 和三栏浏览器工作台；
- 产品选择、PDF 规格证据、预算提示、刷新恢复；
- schema-v2 `saved_draft` v1/v2、完整版本元数据、重复保存幂等和 stale 保存保护；
- append-only 人工确认、confirmed version、结构化 diff 和 confirmed-only 报价 PDF；
- 19 项临时数据库后端集成测试，覆盖迁移、并发、确认、diff、PDF、故障注入和 HTTP；
- 三条固定演示可离线运行；
- 60 项目录/后端/Gateway/评测门禁测试通过；64 项 Agent 测试完成（57 通过、7 项为明确记录的离线语言边界）；
- 英文/中文 README、API 契约和统一项目规划。

当前后端可以生成**不可变 confirmed version 和报价 PDF**；浏览器已接通保存、确认、diff 和 PDF 下载并通过 Chrome 端到端验收。组织者 LLM Gateway 已完成 Story A/B/C 实测；sealed 首轮 10/20 与修复后 20/20 报告均已保留，最终运行 0 fallback。

## 后续工作（按顺序）

1. 完成 5 个案例的真人效率计时；Agent 五案例均正确，中位数 12.705 秒；
2. 仅在声称独立人工审核时，由非作者队员复签 sealed/PDF 技术审核；
3. 彩排、录制 30 分钟视频并完成提交检查。

不要继续增加产品、真实价格、库存、税费、登录、复杂多 Agent 或向量数据库。

## 运行

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

浏览器：`http://127.0.0.1:8000`

验证：

```bash
python scripts/build_data.py
python scripts/validate_data.py
python -m unittest discover -s dell_agent/tests
```

## 关键文档

- `README.md` / `README.zh-CN.md`：项目入口；
- `docs/project-plan-zh.md`：唯一完整规划；
- `docs/api-contract.md`：工具和 HTTP 契约；
- `docs/llm-gateway-setup-zh.md`：组织者 Gateway 配置与验证；
- `data/README.md`：数据、字段、来源与可信边界；
- `data/evaluation/demo_scenarios.jsonl`：三条固定演示。

继续开发前先检查实际代码和测试结果；不要把 holdout 或 expected answers 放入提示词、知识库或运行时上下文。
