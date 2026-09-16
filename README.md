# Quotation Preparation Agent

NUS-ISS Hackathon 选题 **Quotation Preparation**。一个虚构办公设备分销商的报价助手：读取不完整的英文客户询价，主动追问缺失条件，从有原文依据的 Dell 显示器目录筛选型号，用确定性工具计价，经用户确认后保存版本并导出 PDF。

```text
询价 → 提取需求 → 追问 → 搜索产品 → 展示证据 → 用户确认
     → 工具计价 → 保存 v1/v2 → 显示 diff → 导出 PDF
```

## 核心原则

> **模型负责理解和追问；确定性工具独占所有事实和金额。**

模型只做两件事：解释询价、决定调用哪个工具。它不生成单价、不计算总额、不替换型号、不填补未知规格。所有金额是整数分，折扣舍入用 `Decimal` + `ROUND_HALF_UP`，产品事实全部来自冻结目录并可回溯到 PDF 页码。

> ⚠️ **产品规格来自 Dell 官方公开手册；价格、折扣政策和客户询价全部是本项目的模拟数据。**
> 它们不代表 Dell 的报价、库存或商业政策。`calculate_quote` 的返回是**未保存、未审批的草稿**，不是税务发票。工具不保存、不审批、不锁库存、不导出 PDF、不发消息。库存与交期没有数据，一律显示未知。

## 当前状态

数据层和离线确定性工具已完成并通过校验；**Web 应用、Bedrock 实际调用、报价持久化、版本 diff 和 PDF 导出尚未开发**。

| 项目 | 状态 |
|---|---|
| 6 份 Dell 官方手册（522 页，43.9 MB） | 已下载，含 provenance 记录 |
| 12 个显示器型号 + 12 条模拟 SGD 价格 | 已核对，`dataset_version = 2026-09-14.v1` |
| 96 条字段级证据（PDF 页码 + 推导方法） | 已生成 |
| 20 dev + 20 holdout + 3 演示场景 | 已生成（fixture，非实测结果） |
| 三个确定性工具 | 两套实现，均通过测试（见下方"两套工具实现"） |
| 离线测试 | `tests/` 14 项通过；`dell_agent/tests/` 63 项通过、14 项 skip |
| 模型评估 | **未运行**，没有调用过任何模型 API |
| 人工独立抽查 | **未完成**，规格由 assistant 核对，冻结前需队员复核 |
| AWS 资源 | 未创建 |

不需要继续下载产品资料、实时价格、库存或客户数据。

## 快速开始

只需要 Python 标准库，已在 Python 3.9 和 3.14 上验证。目录数据已提交在仓库里，**不需要**跑任何 fetch 或下载脚本。

```bash
git clone <repo> && cd show_me_your_agent_hackason

# 0. 生成本地目录数据库（storage/ 不入版本库，是可重建产物）
python scripts/build_data.py

# 1. 数据完整性校验 + 运行 tests/ 套件（写出 data/validation/report.json）
python scripts/validate_data.py

# 2. dell_agent 全套离线测试
python -m unittest discover -s dell_agent/tests
# → Ran 63 tests ... OK (skipped=14)

# 3. 查产品：USB-C 视频 + 至少 90W 主机供电
python scripts/catalog_tools.py search_products '{"usb_c_video":true,"min_pd_watts":90}'
# → MON-007, MON-008, MON-009, MON-011（按模拟价升序）

# 4. 计价：8 台 P2425HE，预算 SGD 2500
python scripts/catalog_tools.py calculate_quote \
  '{"items":[{"sku":"MON-007","quantity":8}],"budget_cents":250000}'
# → total_cents 231200, within_budget true

# 5. 端到端（确定性 driver，不需要任何云资源）
python -c "
from dell_agent.agent.loop import OfflineDriver
r = OfflineDriver().run('Please quote 8 Dell P2425HE monitors, budget SGD 2500.')
print(r.status, r.quote_draft['total_cents'], r.quote_draft['within_budget'])
"
# → ready_to_quote 231200 True
```

重新提取 PDF 文本是唯一需要第三方库的步骤：`pip install -r scripts/requirements-data.txt`（pypdf）。

## 仓库结构

```text
data/                          # 数据包（详见 data/README.md）
  raw/dell/*.pdf               # 6 份官方手册原件，不覆盖
  raw/download_log.json        # 实际下载时间、地址、字节数
  source_manifest.json         # 来源清单
  extracted/                   # 逐页文本（PDF 页码从 1 开始）
  curated_specs.json           # ★ 已核对事实与页码的维护入口
  synthetic_business.json      # ★ 模拟价格与规则的维护入口
  processed/                   # products / prices / field_evidence / sources / pricing_rules
  agent/catalog.json           # 运行时目录（规格 + 价格 + 规则 + 证据）
  agent/bedrock_tool_config.json   # Converse toolConfig（3 个工具）
  agent/instructions.md        # 系统提示词起点
  agent/knowledge/MON-*.md     # 12 份规格卡片（仅规格，无价格无答案）
  evaluation/                  # dev / holdout / expected_results / demo_scenarios
  validation/report.json       # 校验与离线测试统计
dell_agent/                    # Agent 包（自带一份数据镜像）
scripts/                       # 数据流水线 + 目录工具 CLI
tests/                         # scripts/catalog_tools.py 的测试
storage/catalog.sqlite         # 可重建的目录数据库（非报价库）
docs/                          # 10 天计划、原始三周 workflow
agent.md                       # 团队交接说明
```

`★` 标记的两个文件是唯一应该手工编辑的数据源。`processed/`、`agent/`、`storage/` 全部由 `build_data.py` 生成。

## 数据

12 个 SKU 覆盖 3 种尺寸、4 种分辨率、3 档 USB-C 供电。完整表格、字段语义和来源说明见 [data/README.md](data/README.md)。

三个字段必须区分清楚，它们是本题最容易出错的地方：

| 字段 | 含义 | 常见误解 |
|---|---|---|
| `usb_c_video` | 上行 USB-C/Thunderbolt 口是否支持视频输入 | "有 USB-C 口"不等于能出画面。`MON-010` (U2724D) 的上行口是 **data only** |
| `usb_c_pd_watts` | 上述视频上行口给**主机**的最大供电 | `0` 不代表显示器完全没有 USB 充电能力 |
| `usb_c_downstream_charge_watts` | 下行口给**外设**充电的功率 | P 系列的 15W 下行口不能替代 65/90W 笔记本上行口 |

`screen_inches` 是手册记载的实际可视对角线，不是营销尺寸。`MON-007` 是 23.81 英寸，严格要求"至少 24.0 英寸"时它**不满足**。`stock_quantity` 和 `delivery_lead_days` 恒为 `null`。

## 三个冻结工具

| 工具 | 职责 |
|---|---|
| `search_products` | 结构化条件筛选。`query` 只做型号/SKU/名称关键词匹配，**不解析整句自然语言**；字段为 `null` 视为不满足条件；无匹配返回空，不做静默替换 |
| `get_product` | 单个 SKU 的公开规格、模拟价格、字段级证据（source_id + PDF 页码 + 推导方法）；库存交期报告为不可用 |
| `calculate_quote` | 仅用目录价计算草稿。拒绝自定义单价、非正整数数量、超过 5% 的折扣（拒绝而非截断） |

### 两套工具实现（当前的主要技术债）

同样这三个工具存在**两份独立实现，契约不一致**：

| | `scripts/catalog_tools.py` | `dell_agent/agent/tools.py` |
|---|---|---|
| 错误方式 | 抛 `ToolError` | 返回 `{"error": code, "message": ...}` |
| 错误码 | 大写：`UNKNOWN_SKU`、`MISSING_PRICE`、`DUPLICATE_SKU` | 小写：`unknown_sku`、`missing_price`、`custom_price_forbidden`、`bad_argument` |
| `search_products` 返回 | `{dataset_version, count, products}` | 裸 list |
| `calculate_quote` 返回 | `status: draft_requires_review`，字段名 `items`、含 `subtotal_cents` | `status: draft`，字段名 `lines` |
| 重复 SKU | 拒绝，要求合并数量 | 允许，作为独立行 |
| 折扣上限来源 | 读 `rules.discount_limit_bps` | 硬编码 `500` |

两边的数据文件目前 sha1 完全一致（`catalog.json`、`pricing_rules.json`、`bedrock_tool_config.json`、`instructions.md`、4 个 evaluation jsonl）。但两边各有独立的加载和计算代码，一旦有人只改一边，两套测试会同时"通过"却给出不同的报价结构。**Web 后端接入前必须选定一个为唯一契约**，另一边改为引用或删除。

## 计价口径

```text
行原价 = 单价（分）× 数量
行折扣 = half_up(行原价 × 折扣基点 ÷ 10000)
行净额 = 行原价 − 行折扣
总额   = Σ 行净额 + 配送费（0）
```

SGD，整数分。默认折扣 0，上限 500 bps（5%），数量为正整数。配送费 0，税费未建模，报价有效期政策 7 天。`rule_version = price_version = demo-v1`。

已独立用 `Decimal` 复核的金额锚点（可直接用于回归）：

| 场景 | 期望 |
|---|---|
| `MON-007` × 8 @ 0 bps | `231200`，预算 250000 内 |
| `MON-007` × 10 @ 0 bps | `289000`，超预算 `39000` |
| `MON-009` × 2 @ 500 bps | `66310` |
| `MON-001` × 7 @ 250 bps | `101692` |

折扣必须由用户明确确认，Agent 不得为了凑进预算自行加折扣或改单价。

## Agent 层

`dell_agent/agent/state.py` 是一个纯函数状态机，把一个已解析的客户轮次分类为 8 种状态之一：

```text
ready_to_quote  needs_clarification  explain_limitation  answer_with_evidence
no_match        budget_conflict      rule_violation      invalid_quantity
```

两个 driver 返回同一个 `AgentResult` 形状：`{status, ask_for, candidates, quote_draft, citations, notes, trace}`。

- **`OfflineDriver`**（默认）：纯标准库启发式规则 + 状态机 + 结构化查询，只在判定为 `ready_to_quote` 时才调 `calculate_quote`。不需要任何云资源，用于回归测试和"模型挂了也能演示"的兜底。
- **`ConverseDriver`**（可选）：通过 Bedrock Converse 的 tool-use 循环驱动同样三个工具，系统提示词来自 `instructions.md`，`toolConfig` 逐字取自 `bedrock_tool_config.json`。任何失败（缺 boto3、缺凭据、限流、响应异常）都静默降级到 `OfflineDriver`，降级原因写入 `notes` 和 `trace`。

知识检索（`dell_agent/knowledge.py`）只索引 `agent/knowledge/MON-*.md`，由显式白名单把关。评估数据、预期答案和校验报告**永不进入**运行时知识库。

### 接 Bedrock

```bash
pip install boto3
```

```python
from dell_agent.agent.loop import ConverseDriver
r = ConverseDriver(model_id="<bedrock-model-id>", region="us-east-1").run(
    "We need 8 monitors that charge our laptops over one cable. Budget SGD 2500."
)
print(r.status, r.notes)
```

**`ConverseDriver` 不读环境变量**，`model_id` 必须显式传入，否则它会立刻降级到 `OfflineDriver` 且**不报错**。调试时务必检查 `r.notes` 里有没有 `used the deterministic offline driver`，否则分不清"模型真的跑了"和"悄悄回退了"。凭据通过标准 AWS 配置提供，不写进源码、日志或录屏。

## 测试与可信范围

```bash
python scripts/validate_data.py                      # 数据关系校验 + tests/ 14 项
python -m unittest discover -s dell_agent/tests      # 63 项，其中 14 项 skip
python -m unittest dell_agent.tests.test_pricing     # 单个套件
```

`validate_data.py` 会校验 SKU 唯一性、价格与规则一致性、证据页码落在实际页数内、PDF 字节数与下载记录一致、SQLite 与 `catalog.json` 完全相同、评估集 ID 不重复，然后写出 `data/validation/report.json`。

**14 个 skip 不是缺凭据，是 `OfflineDriver` 自己声明的启发式能力缺口**，包括 13 条 dev/holdout 分类案例和 `DEMO-02`。已知缺口：

- `DEMO-02`（U2724D 的 data-only 陷阱）用功能化表述 "one-cable laptop video" 时检测不到，被判成 `ready_to_quote` 并给出报价 —— 这正是应该被拦住的行为。**这是三条演示故事里最关键的一条，目前是坏的。**
- 未知型号（`XYZ999`）判成 `needs_clarification` 而非 `no_match`
- 数量修改 "Make that 6" 不会往后传递
- "minus two" 未被识别为非法数量
- 多产品组合 "4 P2425E plus 2 S2725QC" 解析不出

这些语义缺口是留给 LLM 路径的。当前状态是：**金额可信，语言理解未接入**。

必须如实声明的边界：40 个自然语言场景由开发 Agent 编写，**未经独立人工审核，也未用真实模型测评**。它们是可用的测试素材，不是准确率证据。`report.json` 里 `model_evaluation` 和 `human_review` 都标记为未完成。不得把 holdout 答案放进提示词或知识库。

## 重建数据

改价格或规则：编辑 `data/synthetic_business.json`，然后

```bash
python scripts/build_data.py      # 重新生成 CSV / catalog.json / 规格卡片 / SQLite
python scripts/validate_data.py
```

改产品事实：编辑 `data/curated_specs.json`（每个字段都要有页码），再跑同样两步。构建脚本不会从新手册自动猜出新字段。

从原始来源完整重建：

```bash
python scripts/download_sources.py                        # 复用已有 PDF，不覆盖固定版本
pip install -r scripts/requirements-data.txt              # pypdf
python scripts/extract_sources.py                         # 逐页文本
python scripts/build_data.py
python scripts/prepare_evaluation.py                      # 会覆盖评估集，手工扩充过就别跑
python scripts/validate_data.py
```

`build_data.py` 已验证是可复现的：在当前数据上重跑不产生任何 git 差异。

## 已知问题

1. **两套工具契约不一致**（见上）。接后端前必须收敛成一套。
2. **`DEMO-02` 在离线路径上是坏的**。要么接 Bedrock 让模型处理功能化表述，要么给离线检测器补上 "one-cable / charge over USB / single cable" 这类同义表述。建议都做，后者能保住兜底演示。
3. **`source_manifest.json` 漏了型号 `P2425`**：`DELL-P25H` 那条只记了 P2225H/P2425H/P2725H，但手册封面还有 P2425（24 英寸 16:10、1920x1200）。`curated_specs.json` 里 `MON-005` 已经用了它。
4. **`download_log.json` 与实际文件不一致**：只有 2 条记录，实际 6 个 PDF 都在。`download_sources.py` 遇到"文件存在但无 provenance"会抛错。
5. **`scripts/`、`tests/`、`agent.md` 尚未提交到 git**（当前仅 95 个文件被跟踪）。`data/README.md` 里引用的所有命令都依赖这些未提交的脚本。
6. **数据未冻结**：还需队员独立抽查 6 个型号、每个核对 2 个字段。

## 下一步

按 [docs/10-day-plan-zh.md](docs/10-day-plan-zh.md) 执行。最近的三件事：

1. 收敛工具契约，冻结入参、返回和错误码
2. 建 FastAPI 与报价业务表（报价、条目、价格与规则快照、版本）
3. Day 3 前打通第一条端到端询价，之后每天用 `DEMO-01` 做一次集成回归

## 来源与许可

产品规格来自 `data/processed/sources.csv` 中链接的 Dell 官方英文手册。原 PDF 保留 Dell 版权，公开可下载不等于开放数据许可；本仓库保存原件用于溯源，公开发布前须检查再分发条款。价格、折扣规则和所有询价均为模拟数据并已在数据中显式标记。

- 数据说明：[data/README.md](data/README.md)
- Agent 包说明：[dell_agent/README.md](dell_agent/README.md)
- 10 天计划：[docs/10-day-plan-zh.md](docs/10-day-plan-zh.md)
- 原始三周 workflow：[docs/quotation-preparation-three-week-plan-zh.md](docs/quotation-preparation-three-week-plan-zh.md)
