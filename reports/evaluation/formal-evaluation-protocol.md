# Sealed holdout 与正式指标协议

## 隔离边界

- 输入：`data/evaluation/sealed_holdout_enquiries.jsonl`；
- 答案：`reports/evaluation/sealed_holdout_expected.jsonl`；
- 独立审核：`reports/evaluation/sealed-holdout-review.csv`；
- 哈希与状态：`reports/evaluation/sealed-holdout-manifest.json`。

应用、Agent prompt、目录和普通回归测试不读取 sealed 输入或答案。`run_formal_evaluation.py` 先完成全部推理并保存 `raw_results.jsonl`，之后才打开答案文件评分。

输入、答案和审核表在首次真实运行前由 `.gitignore` 保持为本地私有文件；公开仓库只保存哈希 manifest、协议和运行器。首次原始结果保存后再按团队提交规则归档。

## 首轮运行

独立审核表 20 条均签核后，先冻结审核状态：

```bash
.venv/bin/python scripts/prepare_sealed_holdout_review.py --finalize
```

只有 20 条记录的 case/hash 均匹配，且每条都有 `PASS`、reviewer 和日期时，manifest 才会更新为 `SEALED_REVIEW_PASSED`。随后运行：

```bash
.venv/bin/python scripts/run_formal_evaluation.py \
  --driver converse \
  --model-id "$BEDROCK_MODEL_ID" \
  --region "$AWS_REGION" \
  --label first-pass
```

正式运行必须满足：

- `driver=converse`；
- `fallback_count=0`；
- `valid_real_model_run=true`；
- 保存 model ID、Region、Git commit、dataset/price/rule version 和输入/答案哈希。

运行器会在推理前校验输入哈希和 manifest 审核状态；全部原始结果逐条落盘后才读取并校验答案哈希。真实运行若未审核或发生 fallback 会返回非零退出码。

## 指标

| 指标 | 项目门槛 |
|---|---:|
| clarification | ≥ 90% |
| selection | ≥ 90% |
| amount | 100% |
| policy_block | 100% |
| evidence | 100% |

脚本还保存 status accuracy、逐案例 failed checks 和失败分类。任何修复后运行必须使用不同 label，例如 `--label fixed-01`，不得覆盖首轮目录。

Offline readiness smoke 和 credential-check 目录只验证运行器及 fallback 门禁，不属于真实模型指标。
