# 五案例人工与 Agent 效率计时协议

## 目的

对同一组 5 个询价分别记录人工流程和 Agent 流程用时。只报告样本数、中位数和范围，不预设提升比例。

## 案例

使用 `manual-timing-input.csv` 中的 `TIME-001` 至 `TIME-005`。人工和 Agent 必须使用相同的冻结目录、价格和规则。

## 人工计时

1. 操作者开始阅读询价时启动计时。
2. 操作者使用目录、价格表和规则完成产品选择、计算或政策阻断。
3. 得到可供复核的结果时停止计时。
4. 运行 `.venv/bin/python scripts/capture_manual_timing.py`，按提示完成 5 次操作；脚本会填写操作者、ISO 时间、秒数、结果核对和备注。
5. 每个案例只记录一次正式观察，不删除较慢结果。

## Agent 计时

安装依赖后运行：

```bash
.venv/bin/python scripts/run_efficiency_timing.py \
  --driver converse \
  --model-id "$BEDROCK_MODEL_ID" \
  --region "$AWS_REGION" \
  --manual-csv reports/evaluation/manual-timing-input.csv \
  --label first-pass
```

计时从调用 Driver 前开始，到结构化 `AgentResult` 返回时停止。若任何案例走 fallback，报告会把 `valid_real_model_timing` 标为 `false`。
真实模型命令只有在无 fallback、5 条 Agent 结果均正确、5 条人工记录完整且均核对为 `PASS` 时才以成功状态结束；否则保留报告并返回非零退出码。

## 验收

- 人工和 Agent 各 5 条记录；
- 每条结果先核对事实、金额或阻断状态；
- 报告包含样本数、中位数、最小值和最大值；
- 首轮数据保留，修复后计时使用新 label 和新目录。
