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

以下事项**仍未**完成：真实模型评测、sealed blind holdout 的非作者审核、正式指标报告、最终 PDF 模板人工复核和人工与 Agent 效率计时。

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
| `pdf-machine-precheck.json` | 标准/长表 PDF 的页数、字段、逐页表头、页脚、45 行及总额/条款检查 | 9 项机器预检通过；独立人工签字待完成 |

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
63 tests passed
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

真实 Bedrock / 大模型：

```text
真实模型首轮评测（dev + holdout）
真实 tool-use trace 与 fallback 检查
记录 model ID、Region、prompt 与各版本
Offline 与真实模型结果对比
```

由 A 在真实首轮前后完成：

```text
由非作者审核新建 sealed holdout 的 expected
正式指标报告：首轮与修复后分开保存
失败分类
```

浏览器 confirmation/diff/PDF 页面已接通，并由 Chrome headless 完成 Story A 的 v1/v2、diff、确认、下载和 PDF 金额一致性验收。人工与 Agent 效率比较仍需 5 条真人计时记录。

## 8. A 侧当前完成情况

```text
[x] 数据冻结审核：24 条 PASS（LAI WENDI，2026-09-20）
[x] expected 审核：40 条 PASS（LAI WENDI，2026-09-20）
[x] 金额复核：15 条 PASS（LAI WENDI，2026-09-21）
[x] B 后端金额一致性核对：3 条 PASS（LAI WENDI，2026-09-21）
[ ] sealed holdout 非作者审核、真实模型评测和正式指标
[x] 浏览器端到端验收：Chrome 真实页面操作通过
[ ] 最终 PDF 模板人工复核与 5 案例真人效率计时
```

## 9. 2026-09-21 后续执行记录

- 数据冻结状态已同步到 `data/validation/report.json`、`freeze-manifest.json`、README 和项目规划。
- 新建 20 条 `SEALED-*` holdout；输入和答案分文件保存，运行器先保存全部推理结果再读取答案。哈希与隔离说明见 `sealed-holdout-manifest.json`，非作者审核表为 `sealed-holdout-review.csv`。
- `run_formal_evaluation.py` 已通过 Offline readiness smoke；它会校验 sealed 输入哈希和审核状态，逐条持久化原始结果后才读取答案。未完成 20 条非作者签核时，真实运行会在推理前拒绝；发生任何 fallback 也会判为无效真实模型运行。
- Chrome 153 真实页面完成 v1/v2 保存、diff、确认、PDF 下载以及页面/快照/PDF 金额一致性验收；报告和截图在 `browser_acceptance/20260921T074342Z/`。
- 9 项异常矩阵全部通过，见 `exception-acceptance.md`。
- 五案例 Agent 计时工具和真人交互计时工具已就绪。Offline readiness 数据有效但不属于真实模型效率指标；真实计时只有在无 fallback、Agent 结果正确且 5 条人工记录完整并核对 PASS 时才通过门禁。
- 2026-09-22 已用排除 `AWS_ACCESS_KEY_ID`、`AWS_SECRET_ACCESS_KEY` 和 `AWS_SESSION_TOKEN` 环境变量的 STS 命令验证 `showme-agent` Profile。随后只读调用 `bedrock:ListFoundationModels` 被 AWS Organizations SCP 显式拒绝；凭证链已就绪，但当前账户/角色尚不能用于发现 Bedrock 模型。

完成 A 的最终交付仍需：非作者签核 sealed expected 与 PDF 模板、解除当前 Bedrock SCP 限制或切换到允许 Bedrock 的账户/角色、取得可调用的 Bedrock model ID，以及 5 次真人计时。

可运行 `.venv/bin/python scripts/check_a_completion.py` 统一检查上述证据门禁；它会写入 `a-completion-status.json`，在所有门禁通过前返回非零退出码。
