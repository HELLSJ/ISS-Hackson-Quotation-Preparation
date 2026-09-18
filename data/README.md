# 报价 Agent 数据包

已下载并整理 **6 份 Dell 官方英文手册，覆盖 12 个显示器型号**。产品规格来自手册；12 个销售价格、折扣和报价政策是本项目的模拟业务数据。下载记录包含实际下载时间，数据版本为 `2026-09-14.v1`。

先使用 [Agent 目录 catalog.json](agent/catalog.json)，或直接调用本文的本地查询和计价工具。无需重新下载、注册 Icecat 或购买数据。

## 从哪些文件开始

| 文件 | 内容 | 使用方式 |
|---|---|---|
| [agent/catalog.json](agent/catalog.json) | 产品规格、模拟价格、规则、字段出处 | 后端直接加载，JSON 保留数字、布尔值和 null |
| [processed/products.csv](processed/products.csv) | 12 个产品规格 | 人工查看和导入；UTF-8，布尔值为 true/false |
| [processed/prices.csv](processed/prices.csv) | 模拟 SGD 销售价格 | 整数分，例如 28900 表示 SGD 289.00 |
| [processed/pricing_rules.json](processed/pricing_rules.json) | 模拟计价规则 | 计价程序读取，不靠模型心算 |
| [processed/field_evidence.csv](processed/field_evidence.csv) | 96 条字段级证据 | 型号、尺寸、分辨率、刷新率、USB-C 功能等对应的 PDF 页码 |
| [processed/sources.csv](processed/sources.csv) | 来源链接和文件信息 | 原件来源、下载日期、页数、使用说明 |
| [../storage/catalog.sqlite](../storage/catalog.sqlite) | 已导入的目录数据库 | products 表包含完整 JSON，prices 表包含模拟价；无客户数据 |
| [agent/bedrock_tool_config.json](agent/bedrock_tool_config.json) | 3 个工具定义 | 对应 Bedrock Converse 的 toolConfig 结构 |
| [agent/instructions.md](agent/instructions.md) | Agent 数据使用说明 | 用于系统提示词的起点 |
| [agent/knowledge/](agent/knowledge/) | 12 份规格知识卡片 | 可选检索输入；不包含价格和评估答案 |
| [evaluation/](evaluation/) | 20 个开发案例、20 个验收案例、3 个演示故事及预期结果 | 用于后续测试，不上传到 Agent 知识库 |
| [validation/report.json](validation/report.json) | 数据校验与离线测试统计 | 区分已测试工具与尚未进行的模型评估 |

## 目录覆盖

下表单价全部为模拟价。`host PD` 专指用于笔记本视频连接的上行口供电；下行口给外设充电另记，不能混用。

| SKU | 型号 | 实际对角线（英寸） | 原生分辨率 | USB-C 视频输入 | host PD（W） | 模拟单价（SGD） |
|---|---|---:|---|---|---:|---:|
| MON-001 | S2425H | 23.8 | 1920x1080 | 否 | 0 | 149 |
| MON-002 | S2725H | 27 | 1920x1080 | 否 | 0 | 189 |
| MON-003 | P2225H | 21.5 | 1920x1080 | 否 | 0 | 179 |
| MON-004 | P2425H | 23.81 | 1920x1080 | 否 | 0 | 209 |
| MON-005 | P2425 | 24.07 | 1920x1200 | 否 | 0 | 229 |
| MON-006 | P2725H | 27 | 1920x1080 | 否 | 0 | 249 |
| MON-007 | P2425HE | 23.81 | 1920x1080 | 是 | 90 | 289 |
| MON-008 | P2425E | 24.07 | 1920x1200 | 是 | 90 | 319 |
| MON-009 | P2725HE | 27 | 1920x1080 | 是 | 90 | 349 |
| MON-010 | U2724D | 27 | 2560x1440 | 否 | 0 | 459 |
| MON-011 | U2724DE | 27 | 2560x1440 | 是 | 90 | 629 |
| MON-012 | S2725QC | 27 | 3840x2160 | 是 | 65 | 499 |

三组 P/S 系列手册覆盖多个型号，已按型号对应的表格和页码分别整理。没有把 WOST（不含支架）版本重复计为新 SKU。当前只有显示器，不含键鼠，也没有为了凑 30 个 SKU 复制相同产品。

### 必须保留的字段含义

- `screen_inches` 是手册记载的实际可视对角线。23.81 不等于严格的 24.0 最小尺寸；客户说“24 寸”时要澄清是否接受市场标称尺寸。
- `usb_c_video` 判断 USB-C/Thunderbolt 上行口是否支持视频输入；U2724D 的 USB-C 上行口是 data only。
- `usb_c_pd_watts` 为上述视频上行口给主机的最大供电。0 不代表显示器完全没有 USB 充电功能。
- `usb_c_downstream_charge_watts` 为 USB-C 下行口外设充电功率。P 系列 15 W 下行口不能替代 65/90 W 笔记本视频上行口。
- `max_refresh_hz` 是原生分辨率下的最大预设刷新率，需要相应主机、接口和线缆。P25H 系列 VGA 最大 60 Hz，100 Hz 使用 HDMI/DP。
- `stock_quantity` 和 `delivery_lead_days` 均为 null：未提供库存与交期，不应承诺有货或明日送达。
- 产品事实的缺失值必须保持 null。当前基础规格已核对齐全，不能将将来新增记录的缺失值填成 false 或 0。

每个字段的 `method` 区分直接规格与标准化推导。例如“没有 USB-C 视频输入”依据完整接口列表及端口方向；P25HE 的外设 15 W 值来自 5 V × 3 A。原文不一定存在与 JSON 完全相同的字段名。

## 立即运行

在项目根目录执行。查询、计价、重建和校验只需要 Python 标准库；只有重新提取 PDF 时需要 pypdf。

查找支持视频和至少 90 W 供电的显示器：

```bash
python scripts/catalog_tools.py search_products '{"usb_c_video":true,"min_pd_watts":90}'
```

预期返回 MON-007、MON-008、MON-009、MON-011，按模拟价格排序。

查看单个型号及原文页码：

```bash
python scripts/catalog_tools.py get_product '{"sku":"MON-007"}'
```

报价 8 台 P2425HE，预算 SGD 2500：

```bash
python scripts/catalog_tools.py calculate_quote '{"items":[{"sku":"MON-007","quantity":8}],"budget_cents":250000}'
```

预期总额 `231200` 分（SGD 2312.00），`within_budget=true`。修改成 10 台后为 SGD 2890.00，超预算 SGD 390.00。

查询 `query` 参数用于型号、SKU 或名称关键词；自然语言由模型转成结构化条件。例如不要把整句“find a 27-inch monitor with USB-C”直接传入 `query`。匹配不到必须返回空列表，不能悄悄更换型号后缀。

## 计价口径

默认折扣 0，上限 500 基点（5%）；数量为正整数。每行原价为单价分数乘数量，行折扣按 half-up 舍入到分，行净额为原价减折扣，总额为行净额之和。配送费设为 0，税费暂未建模，报价有效期政策为 7 天。

所有工具返回的金额是整数分。`calculate_quote` 只计算草稿，不保存版本、不审批、不生成 PDF、不发消息。不要把它的成功返回当作用户已经确认。

## 如何接到 AWS / Bedrock

1. 将 `data/agent/catalog.json` 放在后端可读取的位置；最简单的是与后端部署包一起提供，也可以存入自己的私有 S3 桶后由后端加载。
2. 将 `scripts/catalog_tools.py` 作为后端工具模块；实例化 `CatalogTools()` 后使用 `dispatch(tool_name, arguments)`。
3. 加载 `data/agent/bedrock_tool_config.json` 作为 Converse 请求中的 `toolConfig`，选择支持工具调用且账户可访问的模型。
4. 模型返回工具调用时，由后端执行 `dispatch`，再把 JSON 结果作为对应工具结果交回模型。
5. 如果使用知识检索，仅索引 `agent/knowledge/` 中的规格卡片；价格仍从工具读取并计算。

工具格式依据 [AWS ToolSpecification](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ToolSpecification.html) 与 [Converse 的 toolConfig 定义](https://docs.aws.amazon.com/cli/latest/reference/bedrock-runtime/converse.html)。该配置适用于 Converse 工具调用，不是 Bedrock Agents Action Group 的导入文件。

目前未创建 AWS 资源、未上传数据、未调用任何模型。数据包和离线工具已经可用；云端权限、模型调用循环及应用界面属于后续集成。

## 如何重新下载、提取和构建

### 原始资料已在本地

`data/raw/dell/` 保存 6 份原始 PDF，`data/raw/download_log.json` 保存时间和实际地址。`data/extracted/` 保存逐页文本，PDF 页码从 1 开始。PDF 字体可能导致提取文本出现 `/.null` 等噪声，因此最终产品事实来自逐字段核对，不是未经审阅的自动抽取结果。

### 修改价格或规则后

修改 `data/synthetic_business.json`，然后运行：

```bash
python scripts/build_data.py
python scripts/validate_data.py
```

`build_data.py` 重新生成 CSV、Agent JSON、规格卡片及 `storage/catalog.sqlite`。该数据库是可重建的目录，不应存放客户报价或历史版本。改价后评估集中的预期金额也需重新独立核算；校验失败可以提示这些不一致。

### 从原始来源重新建立

```bash
python scripts/download_sources.py
python -m pip install -r scripts/requirements-data.txt
python scripts/extract_sources.py
python scripts/build_data.py
python scripts/prepare_evaluation.py
python scripts/validate_data.py
```

下载脚本默认复用有下载记录的现有 PDF，防止覆盖固定版本；若源文件更新，应另存新快照后重新核对 `curated_specs.json`。此文件是已检查事实及页码的维护入口，构建脚本不会自动从新手册猜出新字段。`prepare_evaluation.py` 会重建本包的固定测试案例，不要用它覆盖已经手工扩充的评估集。

## 测试与可信范围

已执行 14 项离线工具测试，覆盖精确型号、USB-C 视频与供电、尺寸条件、无匹配、未知值、预算、非法数量、折扣上限、缺价、重复行、自定义单价拒绝和舍入。案例中的已指定报价金额使用独立 Decimal 计算核对。

20 个开发场景和 20 个留出场景由开发 Agent 编写，其自然语言预期行为尚未经独立人工审核，也未用真实模型测评。它们是可用的测试素材，不是“模型准确率 100%”的证据。不得将答案、测试集和校验结果放进运行时知识库。

## 来源和使用

规格源自 `sources.csv` 中链接的 Dell 官方英文手册。原 PDF 保留 Dell 版权；公开下载不等于开放数据许可。本包保存原件供溯源，公开发布原件前检查再分发条件。生成的价格、规则和询价均明确标记为模拟，不代表 Dell 报价、库存或商业政策。

完整项目范围、当前进展和后续 Gate 见 [项目总规划](../docs/project-plan-zh.md)。数据部分已经落地；后续按总规划完成独立冻结、真实 Bedrock、确认/diff/PDF 和正式评估。
