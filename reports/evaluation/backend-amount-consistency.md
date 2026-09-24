# B 后端金额一致性核对（A 侧验证）

**生成日期：** 2026-09-21  
**验证对象：** 最新 `main` 分支（提交 `047a9b3`）的报价后端更新 `feat: complete quote backend lifecycle and handoff`。  
**验证范围：** 后端 API 与 PDF 层的金额一致性；浏览器端到端结果另见 `browser_acceptance/20260921T074342Z/`，真实模型评测另按正式评估协议执行。
**验证方式：** 在独立 git worktree（`iss-main-verify`）运行，不影响 A 的审核工作树。

## 1. 结论

后端“计算 → 保存快照 → 人工确认 → 版本 diff → 导出 PDF”的金额在各阶段逐分一致，且确认与 PDF 阶段不会重新计价。使用 Story A 锚点验证通过。

## 2. B 更新带来的能力

本次 `main` 合并的 B 后端文件：

```text
app/snapshots.py     current snapshot schema 快照校验（逐行 half-up、subtotal/total 强校验）
app/quote_diff.py    版本 diff（只比对已存快照，从不重算）
app/quote_pdf.py     confirmed snapshot 导出 PDF（只渲染冻结 JSON）
app/repository.py    append-only 人工确认
tests/test_quote_backend.py  后端集成测试
output/pdf/*.pdf      示例 PDF
```

## 3. 金额校验点（代码依据）

- `snapshots.py` 的 `validate_draft`：逐行用 `Decimal` half-up 复算 `gross/discount/net`，并强校验 `subtotal_cents`、`total_cents`、`over_budget_cents`，不一致直接拒绝保存。
- `quote_diff.py`：只比较已保存/已确认快照的金额字段，不调用计价逻辑。
- `quote_pdf.py` 的 `render_confirmed_quote`：仅在 `status=confirmed` 时渲染冻结快照，不导入目录或计价模块。

## 4. 端到端验证结果

脚本：`iss-main-verify/scripts/verify_quote_amount_consistency.py`（Story A：first draft=8 台、second draft=10 台 P2425HE）。

| 检查 | tool | saved | confirmed | PDF 显示 | diff 差额 | 超预算 | 结果 |
|---|---|---|---|---|---|---|---|
| 第一份草稿（8 台） | 231200 | 231200 | 231200 | 是 | — | — | 一致 |
| 第二份草稿（10 台） | 289000 | 289000 | 289000 | 是 | — | 39000 | 一致 |
| first-to-second draft diff | — | — | — | — | 57800 | — | 与 289000−231200 一致 |

金额均以分（cents）表示；`SGD 2,312.00` 对应 231200 分。

## 5. 后端测试基线

在验证 worktree 上（使用工作区 `.venv`，已安装 fastapi/uvicorn/reportlab/httpx/pypdf）：

| 套件 | 结果 |
|---|---|
| `scripts/validate_data.py` | 通过（15 项数据/工具检查） |
| `python -m unittest discover -s dell_agent/tests` | 63 通过，7 明确 skip |
| `python -m unittest discover -s tests` | 33 项中 32 通过，1 失败（见第 6 节） |

## 6. 已知环境假失败（不是金额错误）

- 失败用例：`tests/test_quote_backend.py::test_confirmed_pdf_contains_snapshot_amounts`。
- 断言：`len(pdf) > 10000`。
- 原因：`quote_pdf._register_font()` 只在 macOS/Linux 字体路径查找 Unicode TTF；在 Windows 上找不到，回退到内置 Helvetica，PDF 体积约 2975 字节，小于 10000 的断言。
- 影响仅体积：独立验证确认该 PDF 仍有效，且包含 `P2425HE`、`SGD 2,312.00`、模拟数据声明；快照 `total_cents=231200` 正确。
- 结论：**金额、内容、声明均正确，失败仅由字体环境导致。** 若要在 Windows 通过该测试，需要为 PDF 渲染提供可用的 Unicode 字体，属于 B/环境配置事项，不影响 A 的金额一致性结论。

## 7. 人工签核

核对表：`backend-amount-consistency-signed.csv`。3 条记录均由 LAI WENDI 于 2026-09-21 签核为 `PASS`。

## 8. 边界

- 本验证只覆盖后端 API 和 PDF 渲染层。
- 浏览器 confirmation/diff/PDF 已通过 Chrome 端到端验收，证据单独保存在 `browser_acceptance/20260921T074342Z/`。
- sealed holdout 和运行器已建立；组织者 Gateway 真实首轮指标、非作者审核以及人工与真实模型计时仍待完成。
