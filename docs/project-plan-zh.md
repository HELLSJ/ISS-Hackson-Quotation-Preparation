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
- 模型微调、复杂多 Agent、向量数据库或临时增加 Bedrock Knowledge Base；
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

当前代码完成了前两项，第三项属于后续 P0 工作。页面、视频和文档不能把 `saved_draft` 描述成批准报价。

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
| 版本安全 | 不可变快照、内容指纹幂等、stale result ID 阻断 |
| 浏览器工作台 | 三栏页面、候选选择、规格证据、预算、数量修改、刷新恢复 |
| 云失败回退 | Converse 设置或调用失败时显式回退 OfflineDriver |

当前机器报告记录：目录工具测试 15 项通过；Agent 测试 63 项通过，其中 7 项是明确记录的 OfflineDriver 启发式边界。三条固定演示不在 skip 中。

### 4.2 部分完成

| 能力 | 已有部分 | 仍缺部分 |
|---|---|---|
| Bedrock Converse | client、tool-use loop、toolConfig、fallback | 团队账户真实调用、完整结构化结果、有限重试和真实评估 |
| 报价版本 | v1/v2 不可变保存、幂等和 stale 防护 | 显式人工确认、版本元数据、结构化 diff |
| Agent 评估 | dev/holdout fixtures 和预期结果 | 独立审核 expected、真实模型首轮 holdout、失败分类 |
| 审计 | 每轮 `AgentResult.trace` 随消息保存 | 可读工具审计页、CloudWatch/部署日志验证 |
| 证据展示 | 本地官方 PDF 与页码链接 | 发布前确认 PDF 再分发条件或改为来源下载链接 |

### 4.3 未完成

- 非原数据整理者进行的独立数据抽查和正式冻结；
- 可导出版本的人工确认语义；
- v1/v2 结构化差异；
- 报价 PDF 生成和失败重试；
- FastAPI/repository 自动化集成测试；
- 团队 AWS 账户上的真实 Bedrock tool-use；
- 正式 holdout 首轮结果和修复后结果；
- 5 个案例的人工流程与 Agent 流程计时；
- 一键恢复固定演示数据；
- 30 分钟视频、最终许可检查和提交。

### 4.4 不能声称已经完成的事项

- 不能把 fixture 数量写成模型准确率；
- 不能把 OfflineDriver fallback 写成 Bedrock 成功；
- 不能把 15 项工具测试写成完整应用测试；
- 不能把 `saved_draft` 写成已批准报价；
- 不能在未计时前声称“提升 80%”；
- 不能承诺库存、交期、税费或真实 Dell 价格。

## 5. 冻结架构

```text
Browser workbench
  → FastAPI (`app/main.py`)
      → QuotationService
          → OfflineDriver
          → ConverseDriver → Amazon Bedrock Converse
      → `dell_agent.agent.tools.dispatch`
          → frozen `catalog.json` / pricing rules / evidence
      → `storage/app.sqlite`
          → conversations
          → messages + AgentResult/trace
          → immutable quote_versions
      → allow-listed local source PDFs
      → future quote diff / PDF exporter
```

数据库职责必须分开：

- `storage/catalog.sqlite`：从数据包生成的目录缓存，可删除重建，不存客户或报价历史；
- `storage/app.sqlite`：应用运行数据，保存对话和不可变报价草稿版本；
- 后续报价 PDF：只读取 `app.sqlite` 的已确认快照。

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

### Gate A（P0）：数据人工冻结

**主责：A 数据与评估；预计 0.5 天，可与 Gate B 并行。**

工作和验收见第 6.2 节。完成后更新校验报告中的 human review 状态，并固定演示数据库种子。

### Gate B（P0）：真实 Bedrock 调用与结果完整化

**主责：C AWS Agent；B 配合；预计 1 天。**

前置条件：

- 团队 AWS 凭据；
- 明确的 Region；
- 账户可访问且支持 Converse/tool use 的模型 ID；
- 后端最小 IAM 权限；
- `requirements-cloud.txt` 已安装。

工作：

1. 用 Story A 完成第一次真实 `converse` 调用；
2. 确认 `configured_driver=converse`、`used_fallback=false`；
3. 保存真实 `converse_start → toolUse → toolResult` trace；
4. 补齐原生 Converse 的 `ask_for`、`candidates` 和 `citations` 组装；
5. 将工具错误映射到八种业务状态；
6. 对可重试的超时/限流最多重试一次；
7. 用 Story A/B/C 对比 Offline 和 Converse 的事实、金额与阻断结果；
8. 模拟调用失败，确认页面显示 Offline fallback 且不丢状态。

**验收：**三条 Story 的真实模型路径均调用工具；事实和金额来自工具；金额与离线路径逐分一致；无隐式 fallback；失败时回退可见且状态保留。

### Gate C（P0）：确认语义、快照元数据和应用测试

**主责：B 报价后端；D 配合；预计 1 天。**

工作：

1. 明确“保存草稿”和“确认可导出”是两个动作；
2. 增加显式确认 endpoint 或确认 token；
3. 确认前检查客户显示名、型号、数量、折扣和计算状态；
4. 快照补充 `dataset_version`、`price_version`、`rule_version`、客户名、报价日期、有效期和条款；
5. 保留现有 result message ID 前置条件；
6. 给 FastAPI/repository 增加临时数据库测试：消息重放、无 draft、stale ID、重复保存、版本递增、fallback 和并发保护。

**验收：**未确认版本不能导出；确认不会重新定价；旧版本重开金额不变；重复请求不增版本；stale 保存为 409；应用成功和错误路径都有自动化回归。

### Gate D（P1）：版本 diff 与报价 PDF

**主责：B；D 负责页面；A 复核；预计 1–1.5 天。**

工作：

1. 计算两个保存版本之间的条目、型号、数量、折扣和总额差异；
2. 页面版本时间线增加 diff 视图；
3. 选择并固定 PDF 库和版本；
4. 固定模板：报价编号、版本、日期、有效期、客户显示名、产品明细、折扣、总额和模拟条款；
5. 只允许从 confirmed snapshot 导出；
6. PDF 生成不调用模型、不查询最新价格；
7. 导出失败保留草稿并允许重试。

**金额锚点：**

```text
Story A v1: 8 × MON-007 = 231200 cents
Story A v2: 10 × MON-007 = 289000 cents
v2 − v1: 57800 cents
v2 over budget: 39000 cents
```

**验收：**v1 不变；v2 和 diff 正确；页面、数据库和 PDF 逐分一致；长名称、分页、页边距正常；失败后可重试。

### Gate E（P1）：正式评估与异常验收

**主责：A；B/C/D 分析各自失败；预计 1 天。**

前置条件：Gate A–D 通过。

工作：

1. 由非 fixture 作者审核 expected labels；
2. 首次解封 20 条 holdout，保存未经修改的首轮结果；
3. 记录 driver、model ID、Region、prompt、dataset 和规则版本；
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
2. 固定 model、Region、prompt、dataset、price 和 rule 版本；
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
| B：报价后端 | 确认语义、快照 schema、应用测试、diff、PDF | API、不可变 confirmed version、diff、PDF |
| C：AWS Agent | Bedrock 真实调用、结果组装、重试、fallback、trace | 三条 Story 的真实 trace 和模型评估元数据 |
| D：前端与演示 | 确认/diff/PDF 页面、异常入口、恢复、视频 | 完整工作台、演示模式、30 分钟视频 |

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
| 21:00–25:00 | Bedrock 与确定性工具架构 | 真实 tool-use trace、fallback |
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
- [x] FastAPI、SQLite 会话和 saved draft versions；
- [x] 三栏浏览器工作台和本地 PDF 证据；
- [ ] 团队独立数据冻结记录；
- [ ] 真实 Bedrock tool-use trace；
- [ ] 完整 Converse AgentResult 和有限重试；
- [ ] 显式人工确认与完整版本元数据；
- [ ] v1/v2 diff；
- [ ] 报价 PDF 和示例文件；
- [ ] 应用集成测试和异常注入结果；
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