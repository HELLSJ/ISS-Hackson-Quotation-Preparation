# 可追溯报价编制 Agent

[English README](README.md) · [项目总规划](docs/project-plan-zh.md) · [API 与工具契约](docs/api-contract.md)

这是一个面向虚构办公设备分销商的报价工作台：把不完整的英文客户询价转成有证据的产品候选和确定性 SGD 报价草稿，同时把产品选择和最终确认留给销售人员。

```text
客户询价 → 澄清需求 → 查询冻结目录 → 查看原文证据
→ 用户选择产品 → 确定性计价 → 保存不可变草稿版本
→ 对比版本 → 人工确认 → 导出 PDF
```

## 为什么做这个项目

销售行政人员需要反复查目录、核对规格、计算折扣，并在客户修改数量后重做报价。尤其是“需要 USB-C”这样的描述可能只指数据接口，也可能要求一根线同时传视频并给笔记本供电，直接报价很容易选错型号。

本项目采用明确的职责分工：

> **模型负责理解语言和追问；确定性工具拥有所有事实和金额。**

模型和前端不能提供单价、计算总额、静默替换 SKU，或把未知规格变成事实。关键产品字段都能回到 Dell 手册和 PDF 页码。

> [!IMPORTANT]
> 产品规格来自公开可访问的 Dell 手册。价格、折扣规则和客户询价均为比赛模拟数据，不代表 Dell 的报价、库存、交期或商业政策。计算或保存的草稿不是已批准报价，也不是税务发票。

## 当前状态

可用纵向切片和报价后端生命周期已经完成：确定性工具、离线 Agent、FastAPI、SQLite 持久化、三栏工作台、本地证据 PDF、schema-v2 草稿快照、append-only 人工确认、结构化 diff 和 confirmed snapshot PDF。

| 模块 | 状态 |
|---|---|
| 原始资料 | 6 份 Dell 手册，522 页，约 43.9 MB |
| 产品目录 | 12 个显示器 SKU、12 条模拟 SGD 价格 |
| 字段证据 | 96 条，含来源 ID、PDF 页码和方法 |
| 评估素材 | 20 dev、20 holdout、3 条固定演示故事 |
| 唯一工具入口 | `search_products`、`get_product`、`calculate_quote` 共用 dispatcher |
| Offline Agent | 可追问、解释限制、阻断规则、计价和修改 |
| Web 应用 | FastAPI + `app.sqlite` + 三栏工作台 |
| 保存版本 | 经过完整校验的 schema-v2 快照，不可变、幂等并阻止 stale 保存 |
| 人工确认 | append-only confirmed snapshot，精确 token 重试幂等 |
| 版本 diff 和报价 PDF | 后端 API 已完成；PDF 只读取 confirmed snapshot，不重新计价 |
| 自动化校验 | 33 项目录/后端测试；63 项 Agent 测试，7 项明确 skip |
| 真实 Bedrock | **未完成**：尚无经验证的真实模型调用 trace |
| 独立数据复核 | **未完成** |
| 浏览器 confirmation/diff/PDF 操作 | **尚未实现** |
| 正式模型/holdout 评估 | **未完成** |

所有后续工作及验收标准见唯一的[项目总规划](docs/project-plan-zh.md)。

## 快速开始

Web 应用要求 Python 3.10+：

```bash
git clone https://github.com/HELLSJ/ISS-Hackson-Quotation-Preparation.git
cd ISS-Hackson-Quotation-Preparation
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 <http://127.0.0.1:8000>。默认 `OfflineDriver` 不需要云凭据。浏览器保存当前 conversation ID，`storage/app.sqlite` 是消息和报价草稿版本的真实数据源。

服务运行时可在 <http://127.0.0.1:8000/docs> 查看 FastAPI 文档。

### 运行主演示

依次输入：

```text
We need 8 monitors with USB-C. Budget SGD 2500.
Video plus at least 65W charging; 23.8-inch FHD is acceptable.
Choose P2425HE at zero discount.
```

计价工具返回 SGD 2,312.00。保存 v1 后输入：

```text
Change quantity to 10 units.
```

新草稿是 SGD 2,890.00，超预算 SGD 390.00。保存后成为 v2，v1 不会改变。

## 架构

```text
Browser workbench (`app/static/`)
  → FastAPI (`app/main.py`)
      → QuotationService
          → OfflineDriver
          → ConverseDriver → Amazon Bedrock Converse（可选）
      → 唯一工具入口 (`dell_agent.agent.tools.dispatch`)
          → 冻结目录、计价规则和字段证据
      → `storage/app.sqlite`
          → conversations
          → messages + AgentResult/trace
          → immutable quote_versions + append-only confirmations
      → manifest 白名单中的本地 Dell PDF
      → stored-snapshot diff 和 confirmed quote PDF renderer
```

`storage/catalog.sqlite` 是可重建目录缓存；`storage/app.sqlite` 保存应用对话和报价草稿快照。两者都不提交到 Git。

## 三个确定性工具

所有运行路径——CLI、OfflineDriver、ConverseDriver、FastAPI 和测试——均调用：

```python
from dell_agent.agent.tools import dispatch
```

| 工具 | 责任 |
|---|---|
| `search_products` | 使用明确的结构化条件筛选；未知值不满足筛选；无匹配返回空；精确型号阻止后缀替换 |
| `get_product` | 返回 SKU 的公开规格、模拟价格、字段证据，以及不可用的库存/交期 |
| `calculate_quote` | 只使用目录价格、整数分、逐行 half-up 折扣和 500 bps 上限 |

`scripts/catalog_tools.py` 只是 CLI/兼容包装，不包含第二套计价逻辑。完整返回值和错误码见 [docs/api-contract.md](docs/api-contract.md)。

```bash
python scripts/catalog_tools.py search_products \
  '{"usb_c_video":true,"min_pd_watts":90}'

python scripts/catalog_tools.py get_product '{"sku":"MON-007"}'

python scripts/catalog_tools.py calculate_quote \
  '{"items":[{"sku":"MON-007","quantity":8}],"budget_cents":250000}'
```

已核对金额锚点：

| 场景 | 结果 |
|---|---:|
| `MON-007` × 8，0 bps | 231200 分，预算 250000 分以内 |
| `MON-007` × 10，0 bps | 289000 分，超预算 39000 分 |
| `MON-009` × 2，500 bps | 66310 分 |
| `MON-001` × 7，250 bps | 101692 分 |

## 数据和证据

目录覆盖不同尺寸、四档分辨率，以及无/65W/90W USB-C 主机供电。必须区分：

- `usb_c_video`：上行 USB-C/Thunderbolt 是否接收视频；
- `usb_c_pd_watts`：上述视频连接给笔记本的供电；
- `usb_c_downstream_charge_watts`：给外设充电，不能替代笔记本视频/PD；
- U2724D（`MON-010`）是 data-only USB-C；U2724DE（`MON-011`）支持视频和 90W；
- `screen_inches` 是实际可视对角线，23.81 英寸不满足严格 24.0 英寸；
- 当前数据没有库存和交期。

完整 SKU、字段和来源见 [data/README.md](data/README.md)。

### 重建与校验

正常运行不需要重新下载。重建派生数据和目录数据库：

```bash
python scripts/build_data.py
python scripts/validate_data.py
```

只应该人工维护：

- `data/curated_specs.json`：已核对事实和证据页码；
- `data/synthetic_business.json`：模拟价格和规则。

重新提取 PDF 需要：

```bash
.venv/bin/pip install -r scripts/requirements-data.txt
python scripts/extract_sources.py
```

## 测试和可信边界

```bash
.venv/bin/pip install -r requirements-dev.txt
python scripts/build_data.py
python scripts/validate_data.py                            # 15 项数据/工具检查
.venv/bin/python -m unittest discover -s tests            # 33 项目录/后端测试
.venv/bin/python -m unittest discover -s dell_agent/tests # 63 项 Agent 测试
```

当前结果：

- 15 项目录/CLI 契约测试通过；
- 18 项临时数据库后端测试通过，覆盖迁移、快照、并发、确认、diff、PDF、故障注入和 HTTP；
- 63 项 Agent 测试通过，7 项是明确记录的 OfflineDriver 启发式 skip；
- 三条固定演示均在离线路径通过。

这不是模型准确率。40 条自然语言案例仍需独立审核 expected label；holdout 答案和校验报告不得进入系统提示词或运行时知识库。

## 可选 Bedrock 路径

```bash
.venv/bin/pip install -r requirements-cloud.txt
export AGENT_DRIVER=converse
export BEDROCK_MODEL_ID='<supported-bedrock-model-id>'
export AWS_REGION='<enabled-region>'
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

AWS 凭据必须通过标准 credential chain 提供，不能写入源码或 `.env`。页面会显示实际使用 Bedrock 还是 Offline fallback。只有 `used_fallback=false` 且 trace 中存在真实 tool-use 才能算云端验证成功。

当前真实云路径仍未完成：团队还需用自己的 AWS 账户运行三条故事，补齐原生 `ask_for`、候选和引用组装，并为可重试错误增加一次有限重试。

## 三条固定演示

1. **澄清、报价、修订：**8 台模糊 USB-C 需求变成 SGD 2,312 草稿；改成 10 台后是 SGD 2,890，并显示 SGD 390 预算差额。
2. **识别 data-only：**要求 U2724D 一根线传视频和 90W 时必须阻断并展示证据；可以建议 U2724DE，但不能自动选择。
3. **守住规则：**6% 折扣和明日交货要求必须被阻断，因为模拟上限为 5%，交期数据未知。

## 后续关键路径

1. 独立抽查 6 个 SKU × 2 个证据字段并冻结数据；
2. 完成真实 Bedrock tool-use 和结构化 AgentResult；
3. 将已完成的 confirmation/diff/PDF 后端 API 接到浏览器操作；
4. 保留正式 holdout 首轮结果，并将修复后结果分开；
5. 实测 5 个案例，彩排、录制 30 分钟视频并提交。

详细负责人、验收标准、指标、异常矩阵和视频结构见 [docs/project-plan-zh.md](docs/project-plan-zh.md)。

## 仓库结构

```text
app/                    FastAPI、SQLite 生命周期、快照校验、diff/PDF、浏览器工作台
data/                   原始、核对、生成、评估和校验数据
dell_agent/             类型目录、计价、状态机、工具和 driver
docs/api-contract.md    冻结的工具与 HTTP 契约
docs/project-plan-zh.md 唯一项目总规划
scripts/                下载、提取、构建、校验和 CLI
tests/                  目录/CLI 契约与报价后端集成测试
agent.md                工程交接摘要
```

## 来源和许可

产品规格来自 `data/processed/sources.csv` 中链接的 Dell 手册。原 PDF 保留 Dell 版权；公开可下载不代表可自由再分发，公开提交前必须确认许可。所有价格、规则和询价均明确为模拟数据。
