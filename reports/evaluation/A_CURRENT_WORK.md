# A：数据与评估——当前可完成工作记录

**生成日期：** 2026-09-20；最近更新：2026-09-22
**当前范围：** A 的数据冻结、评估、验收和效率证据；不改变冻结数据与报价规则。
**目的：** 保存可追溯工件，并明确区分人工审核、Offline readiness、浏览器验收和真实模型指标。

## 1. 当前结论

机器准备和验证部分已完成：

- 已生成独立人工数据冻结的审查清单；
- 已生成全部 40 个 expected case 的审核清单与自动覆盖差距；
- 已用独立 `Decimal`/`ROUND_HALF_UP` 实现复算 15 条带报价行的 expected 金额；
- 已重建运行时目录和 SQLite catalogue cache；
- 已运行项目机器数据验证；
- 已运行 `OfflineDriver` 回归测试；
- 已记录已有 Offline 限制与评测边界。

人工审核部分现已完成并签核（reviewer：LAI WENDI）：

- 数据冻结审核：24 条全部 PASS（`data-freeze-review-signed.csv`，2026-09-20）；
- expected 审核：40 条全部 PASS（`expected-label-review-signed.csv`，2026-09-20）；
- 金额复核：15 条全部 PASS（`money-reconciliation-signed.csv`，2026-09-21）。

正式 sealed-holdout 评测和 Agent 效率计时现已完成：有效首轮 10/20、0 fallback；两轮修复后分别为 19/20 和 20/20，最终全部计分维度 100%、0 fallback。五案例真实 Gateway 计时 5/5 正确，中位数 12.705 秒，范围 9.025–19.633 秒。仍未完成的是同五案例的真人计时。sealed expected 已完成 20/20 Codex 技术审核并通过哈希门禁；最终 PDF 模板完成 8/8 Codex 技术审核。如果提交材料声称独立人工审核，仍需非作者队员实名复签。

## 2. 新增工件

所有 A 工件位于 `reports/evaluation/`，不改动 `data/` 内的原始事实、价格或 fixture。

| 文件 | 内容 | 当前状态 |
| --- | --- | --- |
| `data-freeze-review.csv` | 12 个 SKU 的 USB-C 视频/主机供电 PDF 人工核对清单模板 | 已生成 |
| `data-freeze-review-signed.csv` | 数据冻结人工签核结果 | 已完成；24 条 PASS，LAI WENDI，2026-09-20 |
| `freeze-manifest.json` | 数据/价格/规则版本、输入 SHA-256、样本说明 | 已生成 |
| `expected-label-review.csv` | 40 条 expected 的审核清单模板、机器断言范围和语义缺口 | 已生成 |
| `expected-label-review-signed.csv` | expected 人工签核结果 | 已完成；40 条 PASS，LAI WENDI，2026-09-20 |
| `expected-coverage-gap.json` | 已自动断言字段、需人工审查字段、7 个 Offline 限制 | 已生成 |
| `money-reconciliation.csv` | 15 条 expected 报价的独立 Decimal 复算模板 | 已生成；机器预检通过 |
| `money-reconciliation-signed.csv` | 金额复核人工签核结果 | 已完成；15 条 PASS，LAI WENDI，2026-09-21 |
| `artifact-summary.json` | 自动生成工件的数量和金额预检汇总 | 已生成 |
| `offline-regression-baseline.md` | 本次数据验证及 Offline 回归的真实基线 | 已生成 |
| `backend-amount-consistency.md` | B 后端金额一致性核对说明（计算=快照=确认=diff=PDF） | 已生成 |
| `backend-amount-consistency-signed.csv` | B 后端金额一致性人工签核结果 | 已完成；3 条 PASS，LAI WENDI，2026-09-21 |
| `pdf-machine-precheck.json` | 标准/长表 PDF 的页数、字段、逐页表头、页脚、45 行及总额/条款检查 | 9 项机器预检通过；8/8 Codex 视觉技术审核通过 |

## 3. 实现方式

新增脚本：`scripts/prepare_a_evaluation_artifacts.py`。

该脚本只使用 Python 标准库，并读取以下冻结输入：

```text
 data/curated_specs.json
 data/synthetic_business.json
 data/processed/field_evidence.csv
 data/processed/prices.csv
 data/processed/pricing_rules.json
 data/evaluation/enquiries_dev.jsonl
 data/evaluation/enquiries_holdout.jsonl
 data/evaluation/expected_results.jsonl
```

运行方式：

```powershell
python scripts/prepare_a_evaluation_artifacts.py
```

### 3.1 数据冻结审核范围

脚本固定生成 **24 条**审查项：12 个 SKU 均审核 `usb_c_video` 和 `usb_c_pd_watts`。这两个字段直接决定 USB-C 筛选、候选推荐和报价是否会把 data-only/downstream charging 错当成笔记本视频或主机供电。

| 审核范围 | 审查字段 | 覆盖目的 |
| --- | --- | --- |
| `MON-001` ～ `MON-006` | `usb_c_video`、`usb_c_pd_watts` | HDMI-only / downstream-only USB-C 与无主机供电边界 |
| `MON-007` ～ `MON-009` | `usb_c_video`、`usb_c_pd_watts` | USB-C 视频 + 90 W 主机供电 |
| `MON-010` | `usb_c_video`、`usb_c_pd_watts` | U2724D 的 data-only USB-C 边界 |
| `MON-011` | `usb_c_video`、`usb_c_pd_watts` | U2724DE Thunderbolt 4 上行视频 + 90 W 主机供电 |
| `MON-012` | `usb_c_video`、`usb_c_pd_watts` | 4K USB-C 视频 + 65 W 主机供电 |

每条记录均带有 SKU、预期值、来源 ID、PDF 页码、本地 PDF 路径、来源 URL、推导方法和原始说明。`independent_human_result` 初始为 `PENDING`，不得自动改为通过。

### 3.2 Expected 审核范围

项目现有 runner 自动断言的字段只有：

```text
status
items
quote total_cents
within_budget
over_budget_cents
ask_for
```

`expected-label-review.csv` 会把其他字段显式列为人工语义审核项，例如：

```text
must_not
port
resolution_by_sku
usb_c_video_by_sku
usb_c_pd_watts_by_sku
acceptable_skus
previous_total_cents
actual_diagonal
cheapest_matching_sku
```

现有仓库里的 `holdout` fixtures 已被常规 Offline 测试读取，因此该列会标记为 `existing_holdout_regression`。它可用于回归，但不能作为正式盲测或真实模型准确率证据。

### 3.3 独立金额预检

脚本不调用生产 `calculate_quote`。它直接读取冻结的 `prices.csv` 和 `pricing_rules.json`，并用独立的：

```python
Decimal(...).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
```

按每行折扣计算总额。当前结果：

```text
15 条包含 items 的 expected 报价
15 条 expected total 与独立 Decimal 总额一致
0 条机器预检失败
```

这证明冻结 fixture 与价格/规则的算术一致；它不取代人工对原始询价预算、折扣语义和复核签名的检查。

## 4. 已运行的验证

### 数据构建和结构验证

```powershell
python scripts/build_data.py
python scripts/validate_data.py
```

结果：

| 项目 | 结果 |
| --- | --- |
| 原始 PDF | 6 份、522 页、43,929,093 bytes，验证通过 |
| 产品与模拟价格 | 12 个 SKU、12 条价格，验证通过 |
| 字段证据 | 96 条，验证通过 |
| Evaluation fixture | 20 dev + 20 existing-holdout，ID 对齐 |
| 顶层工具/数据测试 | 15 项通过、0 失败、0 错误 |

### Offline 回归

```powershell
python -m unittest discover -s dell_agent/tests
```

结果：

```text
57 tests passed
7 explicit skips
0 failures
```

这 7 个 skip 是项目明确记录的 Offline heuristic limitation，不计为通过。完整名单见 `offline-regression-baseline.md`。

## 5. 为 Windows 修复的兼容性问题

本机 PowerShell/Python 默认编码为 GBK。原脚本未指定编码，导致读取 UTF-8 提取资料时出现：

```text
UnicodeDecodeError: 'gbk' codec can't decode byte ...
```

已在以下可重建数据脚本中显式使用 UTF-8：

```text
scripts/build_data.py
scripts/validate_data.py
```

修复后，数据构建和验证均成功。该修复不改变数据值、价格规则或 Agent 行为。

## 6. 独立人工审核完成情况

以下人工任务不能由自动脚本或机器校验替代；当前均已由 LAI WENDI 完成并签核：

1. 数据冻结审核：已打开 `data-freeze-review.csv` 对应的 Dell PDF 页，核对型号范围、数值和端口方向。结果记录在 `data-freeze-review-signed.csv`：24 条 PASS，2026-09-20。
2. expected 审核：已审核 `expected-label-review.csv` 的 40 条预期，含语义字段和业务阻断条件。结果记录在 `expected-label-review-signed.csv`：40 条 PASS，2026-09-20。
3. 金额复核：已对 `money-reconciliation.csv` 场景进行独立人工复算并签字，覆盖零折扣、2.5%、5%、多行、预算内/外和数量修改。结果记录在 `money-reconciliation-signed.csv`：15 条 PASS，2026-09-21。
4. 本轮人工审核未发现需要修复的事实错误。若日后发现错误，应按项目数据流程修正后，重新执行构建、验证和相关脚本，并更新对应 signed 文件。
5. B 后端金额一致性核对：针对最新 `main`（提交 `047a9b3`）的报价后端更新，验证“计算 → 保存快照 → 人工确认 → 版本 diff → 导出 PDF”金额逐分一致。结果记录在 `backend-amount-consistency-signed.csv`：3 条 PASS，2026-09-21；详情见 `backend-amount-consistency.md`。

## 7. 仍未完成的事项

已完成的组织者 LLM Gateway / 大模型证据：

```text
Story A/B/C 真实 tool-use 验收
有效首轮、失败分类和两轮修复后报告
最终 20/20、0 gateway_fallback、全部计分维度 100%
model ID、Gateway URL 哈希、dataset/price/rule 版本均已记录；未记录 API key
```

仍需人工完成：

```text
同五案例的真人操作计时和 PASS 核对
若声称独立人工审核，由非作者队员复签 sealed/PDF 技术审核
```

浏览器 confirmation/diff/PDF 页面已接通；Chrome 完成 Story A 的 v1/v2、diff、确认、下载和 PDF 金额一致性验收。2026-09-22 又完成真实 Gateway 政策边界、交付未知、工具审计和 Markdown 证据表格的 Codex 浏览器技术审核，并完成 50-SKU v2 目录加载与 Lenovo 官方证据显示验收。人工与 Agent 效率比较仍需 5 条真人计时记录。

## 8. A 侧当前完成情况

```text
[x] 数据冻结审核：24 条 PASS（LAI WENDI，2026-09-20）
[x] expected 审核：40 条 PASS（LAI WENDI，2026-09-20）
[x] 金额复核：15 条 PASS（LAI WENDI，2026-09-21）
[x] B 后端金额一致性核对：3 条 PASS（LAI WENDI，2026-09-21）
[x] Story A 真实 Gateway smoke：工具调用、金额和引用通过，无 fallback
[x] Story B/C 真实 Gateway：能力边界与政策边界通过，无 fallback
[x] sealed holdout 20/20 Codex 技术审核与哈希门禁
[x] 正式模型首轮、失败分类和修复后指标：最终 20/20、0 fallback
[x] 浏览器端到端验收：Chrome 真实页面操作通过
[x] 最终 PDF 模板 8/8 Codex 技术审核
[x] 5 案例 Agent 真实 Gateway 计时：5/5 正确，中位数 12.705 秒
[ ] 5 案例真人效率计时
[ ] 可选的 sealed/PDF 非作者人工复签（仅在声称独立人工审核时需要）
```

## 9. 2026-09-21 后续执行记录

- 数据冻结状态已同步到 `data/validation/report.json`、`freeze-manifest.json`、README 和项目规划。
- 新建 20 条 `SEALED-*` holdout；输入和答案分文件保存，运行器先保存全部推理结果再读取答案。哈希与隔离说明见 `sealed-holdout-manifest.json`，审核表为 `sealed-holdout-review.csv`。
- 2026-09-22 完成 20/20 Codex 技术审核：状态语义、澄清字段、SKU、端口方向、多轮修改、定价、预算、折扣上限和非法数量均复核通过；逐条证据保存在本地且已忽略的 `sealed-holdout-review.csv`，避免在正式首轮运行前泄露答案。该记录不冒用团队成员身份；若提交材料称为独立人工审核，应由非作者队员复签。
- `run_formal_evaluation.py` 会校验 sealed 输入哈希和审核状态，逐条持久化原始结果后才读取答案。有效首轮 `20260922T072117Z-gateway-first-pass` 为 10/20；修复后 `fixed-01` 为 19/20，最终 `fixed-02` 为 20/20、全部计分维度 100%、0 fallback。
- Chrome 153 真实页面完成 v1/v2 保存、diff、确认、PDF 下载以及页面/快照/PDF 金额一致性验收；报告和截图在 `browser_acceptance/20260921T074342Z/`。
- 9 项异常矩阵全部通过，见 `exception-acceptance.md`。
- 五案例真实 Gateway Agent 计时已完成：5/5 正确、0 fallback，中位数 12.705 秒，范围 9.025–19.633 秒。真人交互计时模板仍为空，完整比较门禁因此保持未通过。
- 历史记录（已由组织者澄清取代）：2026-09-22 验证过 AWS Profile，但直接模型服务调用受组织策略拒绝。该 Profile 现在只用于 Lightsail 托管。
- 组织者最新说明要求模型推理使用团队 API URL 与 API key。项目已移除直接模型服务依赖，新增 Gateway client、原生/JSON 工具回路、有限重试、显式 fallback、连接检查和评测参数。
- 2026-09-22 团队 Gateway 连通性检查成功；Story A 真实 smoke 调用了 `get_product` 和 `calculate_quote`，返回 231,200 分、8 条引用且无 fallback。脱敏证据：`gateway-smoke-20260922.json`。
- Story B/C 修复过程保留 `first-attempt`、`fixed-01` 和最终通过的 `fixed-02` 报告；最终两条均无 fallback、调用本地工具且未生成违规报价。
- Chrome 真实 Gateway 页面完成政策阻断、交付未知、可展开工具审计和安全 Markdown 表格/链接复验；记录在 `browser_acceptance/20260922T075400Z/`。
- Chrome 153 完成刷新后空白询价、50-SKU v2 目录、Lenovo 8 字段证据、保存、diff、确认和 PDF 导出验收；记录在 `browser_acceptance/20260923T151456Z/`。

完成 A 的最终效率比较仍需 5 次真人计时。若最终陈述包含“sealed expected 与 PDF 已由独立人工审核”，还需一名非作者队员实名复签现有技术审核结果。

可运行 `.venv/bin/python scripts/check_a_completion.py` 统一检查上述证据门禁；它会写入 `a-completion-status.json`，在所有门禁通过前返回非零退出码。
