# Quotation Preparation Agent：项目总规划

本文是项目唯一的总体规划，合并了原始数据 workflow 与 10 天开发计划，并按照当前仓库的真实进展重新排序。后续开发、验收、演示和提交均以本文为准。

## 1. 项目目标

批发和分销公司的销售行政人员收到客户询价后，需要查目录、确认规格、核对价格、计算折扣并制作报价文件。多产品、信息不完整或客户修改数量时，这套流程重复、耗时且容易出现事实和金额不一致。

本项目把问题具体化为一个虚构办公设备分销商的 Dell 显示器报价助手：

```text
英文客户询价
  → 提取已知需求
  → 对缺失、含糊或冲突字段追问
  → 从本地目录筛选产品
  → 展示规格证据
  → 用户选择产品并确认数量、折扣
  → 确定性工具计价
  → 保存不可变报价版本
  → 展示版本差异
  → 用户确认后导出 PDF
```

成功标准不是“模型能生成一份看起来像报价的文字”，而是把询价转成一份**可审核、可追溯、可修改、可复算、可导出**的报价，并在信息不足或违反规则时拒绝生成错误结果。

## 2. 冻结范围

### 2.1 本次比赛范围

- 输入：英文自然语言询价，可包含多个型号、规格、数量、预算和折扣；
- 产品：本地冻结目录中的 12 个 Dell 显示器 SKU；
- 产品事实：Dell 官方英文手册中的公开规格；
- 价格与规则：明确标记为 synthetic/demo 的 SGD 模拟销售价和业务规则；
- 折扣：默认 0，上限 500 bps（5%），必须由用户明确提出或确认；
- 输出：产品候选、规格证据、报价草稿、保存版本、版本差异和报价 PDF；
- 人工控制：选择、确认、保存和导出是明确动作；
- 未知数据：库存、交期和税费不能推断，必须显示未知或转人工确认。

### 2.2 明确不做

- 扩展到 30 个产品或增加键鼠、打印机等品类；
- 实时电商价格、真实库存和配送计算；
- 税费、多币种和复杂企业审批流；
- 登录、多租户和复杂权限；
- 真实发送邮件、锁库存、创建订单或采购单；
- 模型微调、复杂多 Agent、向量数据库或临时增加云端 Knowledge Base；
- 为视频效果增加与核心流程无关的动画。

任何新增需求必须直接改善三条演示故事或验收指标，否则进入赛后路线图。

## 3. 核心设计原则

### 3.1 模型处理语言，工具拥有事实和金额

模型只负责理解客户语言、发现缺项、追问和选择工具。以下内容不能由模型或前端生成：

- 产品规格；
- SKU 和产品替换；
- 单价；
- 折扣上限；
- 行金额、总额和预算差额。

唯一运行时工具入口是：

```python
from dell_agent.agent.tools import dispatch
```

三个冻结工具是：

| 工具 | 责任 |
|---|---|
| `search_products` | 使用结构化条件筛选目录；无匹配返回空，不静默替换 |
| `get_product` | 返回一个 SKU 的规格、模拟价格和字段级 PDF 证据 |
| `calculate_quote` | 使用服务器目录价和固定规则计算未确认草稿 |

工具和 HTTP 契约见 [api-contract.md](api-contract.md)。

### 3.2 未知不等于否

新增产品的未知规格必须保留为 `null`。只有官方资料明确无该能力时才可填 `false` 或 `0`。库存和交期当前始终未知；“有 USB-C 接口”也不等于支持 USB-C 视频或给笔记本供电。

### 3.3 报价必须可复现

所有金额使用整数分。行折扣使用 half-up 舍入：

```text
行原价 = 单价（分）× 数量
行折扣 = half_up(行原价 × 折扣基点 ÷ 10000)
行净额 = 行原价 − 行折扣
总额   = Σ 行净额 + 配送费（当前为 0）
```

报价版本必须保存产品名、SKU、数量、单价、折扣、金额，以及数据/价格/规则版本。旧版本不能因目录更新而变化；PDF 只能基于保存并确认的快照生成，导出时不能重新让模型生成事实或金额。

### 3.4 保存草稿不等于人工确认

系统需要区分：

1. `draft`：工具刚计算出的未保存草稿；
2. `saved_draft`：已保存的不可变版本，但仍未批准；
3. `confirmed/exportable`：用户明确确认、通过完整性检查、可以导出 PDF 的版本。

当前后端已完成三个状态及其强制边界：`draft` 只存在于计算结果，schema-v2 `saved_draft` 是不可变未批准版本，`confirmed/exportable` 通过独立 append-only confirmation 记录产生。浏览器已接入确认、diff 和 PDF 按钮并通过端到端验收。

## 4. 当前基线

### 4.1 已完成

| 能力 | 当前实现 |
|---|---|
| 原始数据 | 6 份 Dell 官方英文 PDF，共 522 页、约 43.9 MB |
| 产品目录 | 12 个型号、12 条模拟 SGD 价格 |
| 字段证据 | 96 条，包含来源 ID、PDF 页码和推导方式 |
| 评估素材 | 20 条 dev、20 条 holdout、3 条固定演示故事 |
| 数据构建 | 可重建 CSV、Agent JSON、知识卡和 `storage/catalog.sqlite` |
| 唯一工具契约 | `dell_agent.agent.tools.dispatch`；CLI、Agent 和 API 共用 |
| 离线 Agent | 澄清、查询、限制解释、规则阻断、计价和多轮修改 |
| 演示回归 | Story A/B/C 均可在 OfflineDriver 运行 |
| FastAPI | 产品、证据 PDF、会话、消息、计价、保存和读取版本接口 |
| 业务存储 | `storage/app.sqlite` 保存 conversations、messages、quote_versions |
| 版本安全 | schema-v2 完整快照、内容指纹幂等、stale result ID 阻断 |
| 人工确认 | 独立 append-only confirmation，精确 token 重试幂等，旧 schema 不可确认 |
| 版本 diff | 只比较存储快照，支持 added/removed/changed、金额及元数据差异 |
| 报价 PDF | ReportLab 从 confirmed snapshot 生成，不调用 Agent、目录或计价工具 |
| 应用测试 | 19 项临时数据库测试覆盖迁移、并发、确认、diff、PDF、故障注入和 HTTP |
| 浏览器工作台 | 三栏页面、候选选择、规格证据、预算、数量修改、刷新恢复 |
| 云失败回退 | Gateway 配置或调用失败时显式回退 OfflineDriver |

当前机器报告记录：15 项目录工具测试通过；19 项后端生命周期测试通过；Agent 测试 63 项通过，其中 7 项是明确记录的 OfflineDriver 启发式边界。三条固定演示不在 skip 中。

### 4.2 部分完成

| 能力 | 已有部分 | 仍缺部分 |
|---|---|---|
| 组织者 LLM Gateway | client、原生/JSON tool loop、有限重试和结构化结果完成；Story A 真实 smoke 通过 | Story B/C 真实验证和正式评估 |
| 报价版本与页面 | schema-v2 保存、确认、diff、PDF、故障注入、页面操作和自动化验收 | A 独立复核最终 PDF 模板 |
| Agent 评估 | dev/holdout fixtures 的 expected 已独立审核；新建 sealed holdout 与隔离运行器已就绪 | sealed expected 非作者审核、真实模型首轮结果和失败分类 |
| 审计 | 每轮 `AgentResult.trace` 随消息保存 | 可读工具审计页、CloudWatch/部署日志验证 |
| 证据展示 | 本地官方 PDF 与页码链接 | 发布前确认 PDF 再分发条件或改为来源下载链接 |

### 4.3 未完成

- 组织者 Gateway 的 Story B/C 真实 tool-use 与正式评测；
- 正式 holdout 首轮结果和修复后结果；
- 5 个案例的人工流程与 Agent 流程计时；
- 一键恢复固定演示数据；
- 30 分钟视频、最终许可检查和提交。

### 4.4 不能声称已经完成的事项

- 不能把 fixture 数量写成模型准确率；
- 不能把 OfflineDriver fallback 写成 Gateway 成功；
- 不能把 15 项数据/工具测试或 19 项后端测试写成模型准确率；
- 不能把 `saved_draft` 写成已批准报价；
- 不能在未计时前声称“提升 80%”；
- 不能承诺库存、交期、税费或真实 Dell 价格。

## 5. 冻结架构

```text
Browser workbench
  → FastAPI (`app/main.py`)
      → QuotationService
          → OfflineDriver
          → GatewayDriver → 组织者 LLM Gateway
      → `dell_agent.agent.tools.dispatch`
          → frozen `catalog.json` / pricing rules / evidence
      → `storage/app.sqlite`
          → conversations
          → messages + AgentResult/trace
          → immutable quote_versions + append-only quote_confirmations
      → allow-listed local source PDFs
      → stored-snapshot diff / confirmed-only PDF exporter
```

数据库职责必须分开：

- `storage/catalog.sqlite`：从数据包生成的目录缓存，可删除重建，不存客户或报价历史；
- `storage/app.sqlite`：应用运行数据，保存对话、不可变 schema-v2 草稿和 append-only confirmed snapshots；
- 报价 diff 和 PDF：只读取 `app.sqlite` 的存储快照，不重新查询目录或计价。

## 6. 数据准备与可信链

完整可复现流程如下。当前数据已经完成这些机器步骤，不需要日常开发时重复下载：

```text
source_manifest.json
  → download_sources.py（下载并保存 provenance）
  → raw/dell/*.pdf（原件不覆盖）
  → extract_sources.py（逐页文本）
  → curated_specs.json（人工核对事实与页码）
  → synthetic_business.json（模拟价格和规则）
  → build_data.py
      → processed/*.csv
      → agent/catalog.json
      → agent/knowledge/MON-*.md
      → storage/catalog.sqlite
  → validate_data.py
```

### 6.1 数据维护入口

只直接编辑：

- `data/curated_specs.json`：已核对规格和证据页码；
- `data/synthetic_business.json`：模拟价格和业务规则。

`data/processed/`、`data/agent/catalog.json`、知识卡和 `storage/catalog.sqlite` 均由构建脚本生成。

### 6.2 数据独立冻结（P0）

由一名未参与原始整理的队员完成：

1. 从 12 个产品抽 6 个；
2. 覆盖 FHD、QHD、4K、无 USB-C 视频、65W 和 90W；
3. 每个产品抽 2 个字段；
4. 打开 `field_evidence.csv` 指定的 PDF 页；
5. 核对数值、型号区段和端口方向；
6. 记录 reviewer、结果和问题；
7. 重新运行 `python scripts/validate_data.py`；
8. 将 `2026-09-14.v1` 标记为团队冻结基线。

**验收：**12 个抽查点全部正确且可打开；机器校验 0 错误；之后只能修事实错误，不能随意改 SKU、价格或演示金额。

### 6.3 来源和许可

规格来自 `data/processed/sources.csv` 中列出的 Dell 官方英文手册。公开可下载不等于开放数据许可。公开提交原 PDF 前必须复核再分发条件；如不允许，应只发布事实字段、来源链接和获取说明。价格、规则和询价是模拟数据，界面、PDF 和视频都必须明确标记。

## 7. 用户工作流与状态

Agent 对外使用八种状态：

```text
ready_to_quote       needs_clarification
explain_limitation   answer_with_evidence
no_match             budget_conflict
rule_violation       invalid_quantity
```

基本规则：

- 没数量：追问，不默认 1；
- 裸 “USB-C”：追问是否需要视频和主机供电；
- 严格尺寸：使用实际可视对角线，不把 23.81 当作满足 24.0；
- 指定型号冲突：解释并给证据，不自动替换；
- 建议替代项：必须等用户选择后才能报价；
- 超预算：显示差额，不偷偷改价或增加折扣；
- 超 5% 折扣：拒绝，不截断成 5%；
- 缺价或价格工具失败：阻断报价；
- 模型失败：显示 fallback，保留对话和草稿；
- 重复保存：返回原版本，不新建重复版本；
- stale 页面保存：返回 409，要求刷新后再确认。

## 8. 剩余工作：按 Gate 推进

后续不再按已经过去的 Day 1–Day 6 重复排期，而按以下 Gate 顺序推进。P0 是提交关键路径，P1 是正式验收关键路径，P2 是视频和交付。

### Gate A（P0）：数据人工冻结——已完成

**主责：A 数据与评估。状态：24 条证据核对全部 PASS，`2026-09-14.v1` 已冻结。**

工作和验收见第 6.2 节。完成后更新校验报告中的 human review 状态，并固定演示数据库种子。

### Gate B（P0）：组织者 LLM Gateway 迁移与真实调用

**主责：C Gateway Agent；B 配合。代码迁移和 Story A 真实 smoke 已完成；Story B/C 与正式评测待执行。**

**2026-09-22 状态：**项目已切换为 `GatewayDriver`。团队 Gateway 连通性验证通过；Story A 真实调用返回 `ready_to_quote`，执行 `get_product → calculate_quote`，总额 231,200 分、8 条引用、无 fallback。脱敏证据见 [`gateway-smoke-20260922.json`](../reports/evaluation/gateway-smoke-20260922.json)。旧 SQLite `converse` 会迁移为 `gateway`。

已完成：

1. `LLM_GATEWAY_URL`、`LLM_GATEWAY_API_KEY`、`LLM_MODEL` 三项环境配置；
2. Ollama 兼容 `/api/chat` + `X-API-Key`，以及 `/v1` OpenAI 兼容地址；
3. 原生 `tool_calls` 与 JSON `{tool,args}` 工具请求回路；
4. 所有工具在本地通过 `dispatch` 执行，事实和金额不交给模型；
5. HTTP 429/5xx、网络超时最多重试一次；失败写入 `gateway_fallback`；
6. API key 不进入 trace、数据库或评测报告；报告只保存 Gateway URL 哈希；
7. 应用、评测、效率计时、UI 标签、tool schema 和配置文档统一切换；
8. 自动化覆盖原生调用、JSON fallback、超时 fallback、请求头和旧数据库迁移。

真实 API 后续：

1. 用 Story B/C 确认 `configured_driver=gateway`、`used_fallback=false`；
2. 保存 Story B/C 的真实 `gateway_start → gateway_turn_* tool → final_text` trace；
3. 完成 sealed holdout 首轮评测和真实效率计时。

**验收：**三条 Story 的真实 Gateway 路径均调用本地工具；事实和金额来自工具；金额与离线路径逐分一致；无隐式 fallback；失败时回退可见且状态保留。

### Gate C（P0）：确认语义、快照元数据和应用测试——后端已完成

**主责：B 报价后端。状态：完成并通过自动化测试。**

已交付：

1. `draft → saved_draft → confirmed/exportable` 明确分离；
2. schema-v2 快照包含 line ID、型号、金额、budget、dataset/price/rule version、报价日期、有效期和条款；
3. 启动时将旧行原样迁移为不可确认的 `legacy_saved_draft`，不伪造历史 provenance；
4. result message ID 阻止 stale 保存，source result 和内容指纹保证幂等；
5. `POST /api/quotes/{id}/confirm` 通过精确 snapshot token 创建 append-only confirmed snapshot；
6. malformed arithmetic、旧 schema、旧版本、错误 token 和不同确认重试均被阻断；
7. 临时 SQLite 测试覆盖迁移、四线程并发保存、确认和 HTTP 生命周期；数据库保存故障注入验证草稿保留及重试。

**页面接入状态：**客户名、确认状态、确认按钮、版本 diff 和 PDF 下载已接入现有 API，并通过 Chrome 端到端验收。

### Gate D（P1）：版本 diff 与报价 PDF——后端已完成

**主责：B/D。状态：后端 API、renderer、页面操作和 Chrome 端到端验收完成。**

已交付：

1. `GET /api/quotes/{from}/diff/{to}` 返回 added/removed/changed、数量/折扣/金额 delta 和元数据变化；
2. schema-v2 使用稳定 line ID，legacy 使用明确标记的 SKU occurrence fallback；
3. ReportLab 5.0.1 固定依赖和分页表格模板；
4. `GET /api/quotes/{id}/pdf` 只允许 confirmed schema-v2 snapshot；
5. PDF 包含报价号、版本、客户、日期、有效期、确认人、产品明细、总额、模拟条款和版本 provenance；
6. renderer 不导入 Agent、目录或计价工具，导出不会重新定价；
7. pypdf 测试从实际 PDF 提取并核对客户、P2425HE 和 SGD 2,312.00；PDF 渲染故障注入验证 confirmed snapshot 保留及重试。

**仍需 A 完成：**人工核对最终模板和分页。

### Gate E（P1）：正式评估与异常验收

**主责：A；B/C/D 分析各自失败；预计 1 天。**

前置条件：Gate A–D 通过。

工作：

1. 由非 fixture 作者审核 sealed holdout expected labels；
2. 首次解封 20 条 holdout，保存未经修改的首轮结果；
3. 记录 driver、model ID、Gateway URL 哈希、prompt、dataset 和规则版本，不保存 API key；
4. 将失败分为需求理解、状态机、工具参数、模型波动、应用或数据问题；
5. 修复根因，只重测相关案例；
6. 首轮和修复后结果分开保存；
7. 独立人工复算至少 5 张报价；
8. 测试缺价、无匹配、非法数量、超折扣、模型超时、数据库失败、PDF 失败和重复点击；
9. 选择 5 个相同询价，分别记录人工和 Agent 完成时间。

**建议门槛：**

| 指标 | 门槛 |
|---|---:|
| 必填字段追问正确率 | ≥ 90% |
| 产品筛选正确率 | ≥ 90% |
| 金额正确率 | 100% |
| 政策违规阻断率 | 100% |
| 关键规格证据覆盖率 | 100% |
| 页面/快照/PDF 一致率 | 100% |

效率只报告样本数、中位数和范围，不写预设提升比例。holdout、expected answers 和校验报告不能进入系统提示词或知识库。

### Gate F（P2）：功能冻结、彩排和提交

**主责：D 演示与视频；全员验收；预计 1.5–2 天。**

工作：

1. 增加一键恢复固定演示数据；
2. 固定 model、Gateway 配置哈希、prompt、dataset、price 和 rule 版本；
3. 输出评估表、失败案例和人工复算结果；
4. 从干净环境完整启动并走 Story A/B/C；
5. 检查源码、日志、终端历史和录屏没有凭据或客户数据；
6. 检查公开数据包的许可范围；
7. 彩排一次完整 30 分钟；
8. 功能冻结后只修阻断演示、金额、事实、安全和提交问题；
9. 录制、剪辑、全片检查并提交；
10. 保存提交确认信息。

## 9. 四人协作分工

| 成员 | 主责 | 后续交付 |
|---|---|---|
| A：数据与评估 | 人工冻结、expected 审核、holdout、金额复核、指标 | 冻结记录、首轮/修复后报告、计时结果 |
| B：报价后端 | 确认语义、schema migration、应用测试、diff、PDF、故障注入和 API 交接已完成 | 维护 API；向 D 提供接入契约，向 A 提供模板复核样本 |
| C：Gateway Agent | 组织者 API 真实调用、结果组装、重试、fallback、trace | 三条 Story 的真实 trace 和模型评估元数据 |
| D：前端与演示 | 确认/diff/PDF 页面、异常入口、恢复、视频 | 完整工作台、演示模式、30 分钟视频 |

### A：数据与评估执行清单（2026-09-21）

- [x] 数据独立冻结：24 条证据核对全部 PASS，冻结记录见 `reports/evaluation/data-freeze-review-signed.csv`。
- [x] expected 审核：40 条全部 PASS，并记录机器断言范围与 7 个 Offline 限制。
- [x] 金额复核：15 条独立 Decimal/人工复算全部 PASS。
- [x] B 后端金额一致性：计算、保存、确认、diff 与 PDF 的 3 条锚点全部 PASS。
- [ ] sealed blind holdout 已建立并与运行时隔离；仍需非作者完成独立 expected 审核。
- [ ] 使用组织者 LLM Gateway 运行真实首轮评测，保存原始结果、trace 和脱敏运行元数据。
- [ ] 输出正式指标、失败分类及修复后独立报告。
- [x] Chrome 完成页面保存 v1/v2、diff、确认、下载及页面/快照/PDF 金额一致性验收；证据在 `reports/evaluation/browser_acceptance/`。
- [ ] A 人工复核最终 PDF 模板和分页。
- [ ] 完成 5 个案例的人工/Agent 计时，报告样本数、中位数和范围。

A 收口时运行 `.venv/bin/python scripts/check_a_completion.py`；只有生成的 `reports/evaluation/a-completion-status.json` 中全部门禁为 `passed=true`，才能把 A 标为完成。

### B：报价后端执行清单（2026-09-20）

此清单只跟踪 B 可交付的后端工作；D 的页面实现和 A 的独立模板复核由各自主责验收。

- [x] 确认 `draft → saved_draft → confirmed`、schema-v2 快照和旧版本迁移；临时 SQLite 测试已覆盖。
- [x] 完成保存/确认的幂等、stale 保护与并发测试；未确认版本不可导出。
- [x] 完成只比较保存快照的版本 diff API 与 confirmed-only PDF API；API 契约已记录。
- [x] 补齐数据库保存失败与 PDF 生成失败的故障注入，验证状态保留及重试路径；后端 19 项通过。
- [x] 用 `scripts/generate_pdf_qa_samples.py` 可复现生成并渲染检查[标准报价](../output/pdf/quotation-qa-standard.pdf)（1 页）和[长表报价](../output/pdf/quotation-qa-long.pdf)（5 页）；`pdf-machine-precheck.json` 的 9 项页数、字段、跨页表头、45 行、总额/条款和页脚检查通过，样本仍待 A 独立人工签字。
- [x] 核对 D 所需的保存、确认、diff、下载接口与响应示例；Story A 的 v1/v2 HTTP 链路已通过，调用顺序和错误恢复见 [API 契约](api-contract.md#browser-integration-handoff-for-d)。
- [x] 运行相关回归并同步本文、API 契约和交付清单的最终状态；当前目录/后端/Gateway/评测门禁 47 项通过，Agent 63 项通过（7 项明确 skip），`git diff --check` 通过。

B 的后端交付已完成。D 的浏览器按钮和 A 的独立模板验收仍由各自主责完成；A 可用上面的两份 QA PDF 核对合成价格、行明细、分页表头、条款和版本 provenance。

协作规则：

- 工具或 HTTP 契约变更必须同步 [api-contract.md](api-contract.md)；
- A 不直接修改后端金额逻辑，B/C/D 不改产品事实；
- C 不把价格和金额写入提示词；D 不在前端计算金额；
- 每天至少用 Story A 做一次端到端 smoke；
- 每项功能由非作者验收一次；
- 发现事实、金额或证据错误当天修复，不留到录制前。

## 10. 三条固定演示故事

### Story A：模糊询价、澄清、报价和修订

1. 客户：`We need 8 monitors with USB-C. Budget SGD 2,500.`
2. Agent 追问 USB-C 视频和笔记本供电需求；
3. 客户确认视频、至少 65W，23.8 英寸 FHD 可接受；
4. 用户选择 P2425HE；
5. 工具计算 8 台 SGD 2,312；
6. 保存 v1；
7. 客户改为 10 台；
8. 工具计算 SGD 2,890，超预算 SGD 390；
9. 保存 v2，展示差异并导出对应 PDF。

### Story B：USB-C data-only 规格陷阱

客户要求 4 台 U2724D，并要求一根线完成笔记本视频和 90W 供电。系统必须用官方手册证据指出 U2724D 上行 USB-C 是 data-only，不能生成错误报价；可以建议满足条件的 U2724DE，但只有用户明确选择后才能计价。

### Story C：折扣和交期边界

客户要求 5 台 S2725QC、6% 折扣并保证明天交货。系统必须拒绝超过 5% 的折扣，不得在缺少库存和物流数据时承诺交期，也不能把结果标记为已批准。

## 11. 30 分钟视频结构

| 时间 | 内容 | 画面证据 |
|---|---|---|
| 00:00–03:00 | 人工报价痛点与目标 | 原始询价和手工流程 |
| 03:00–06:00 | 数据来源、公开规格与模拟价格边界 | PDF、CSV、来源记录 |
| 06:00–14:00 | Story A 完整流程 | 追问、候选、证据、v1/v2、diff、PDF |
| 14:00–18:00 | Story B 规格陷阱 | U2724D/U2724DE PDF 页码 |
| 18:00–21:00 | Story C 政策边界 | 5% 阻断和交期未知 |
| 21:00–25:00 | 组织者 Gateway 与确定性工具架构 | 真实 tool-use trace、fallback |
| 25:00–28:00 | holdout、金额核对和耗时 | 首轮结果、失败项、实测数据 |
| 28:00–30:00 | 交付结果和赛后路线 | 最终报价、可扩展 ERP/CRM 接口 |

每个技术观点后紧跟可见证据，不连续讲幻灯片。若剪去等待、使用回放或 fallback，必须在画面中说明。

## 12. 异常验收矩阵

| 场景 | 正确结果 |
|---|---|
| 未提供数量 | 追问，不默认 1 |
| 找不到型号 | 无匹配，不编 SKU 或价格 |
| 必要规格未知 | 标记待确认，不算满足 |
| 预算不足 | 显示差额，不偷偷改条件 |
| 请求 6% 折扣 | 阻止，显示 5% 上限 |
| 自定义单价 | 工具拒绝 |
| 价格查询失败 | 阻止确认和导出 |
| 模型失败 | 保留状态，显示 fallback，可手动继续 |
| stale 页面保存 | 409，不保存未展示的新草稿 |
| 重复点击保存 | 返回同一版本 |
| 数据库保存失败 | 保留页面草稿，可重试 |
| PDF 失败 | 保留 confirmed snapshot，可重试 |
| 库存或交期请求 | 显示未知，转人工确认 |

任何异常都不能产生一份“看起来正常但事实或金额错误”的已确认报价。

## 13. 最终交付清单

- [x] 可复现数据准备脚本和来源记录；
- [x] 12 个产品、模拟价格、规则和字段证据；
- [x] 唯一确定性工具层；
- [x] OfflineDriver 和三条固定演示回归；
- [x] FastAPI、SQLite 会话和 schema-v2 saved draft versions；
- [x] append-only 人工确认与不可变 confirmed snapshots；
- [x] v1/v2 结构化 diff API；
- [x] confirmed-only 报价 PDF renderer 和下载 API；
- [x] 19 项后端 migration/concurrency/lifecycle/diff/PDF/fault-injection/HTTP 测试；
- [x] 三栏浏览器工作台和本地规格 PDF 证据；
- [x] 团队独立数据冻结记录；
- [x] Story A 组织者 Gateway 真实 tool-use smoke 与脱敏证据；
- [ ] Story B/C 真实 tool-use trace；
- [x] Gateway AgentResult、原生/JSON 工具回路和有限重试；
- [x] confirmation/diff/报价 PDF 的浏览器操作；
- [x] 数据库保存与 PDF 渲染故障注入结果；
- [ ] 正式 holdout 首轮/修复后报告；
- [ ] 5 个案例人工/Agent 计时；
- [ ] 30 分钟视频和提交确认。

## 14. 每日收工门禁

每天结束前至少完成：

1. 从干净或已知状态启动应用；
2. 完整运行 Story A 到当前最远 Gate；
3. 验证金额锚点；
4. 打开至少一个证据 PDF 页；
5. 检查 fallback 状态是否真实；
6. 运行受影响测试；
7. 记录新发现的阻塞项和负责人。

达到 Gate F 的功能冻结后，只接受影响事实、金额、安全、演示和提交的问题。
