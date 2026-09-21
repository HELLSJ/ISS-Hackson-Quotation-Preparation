# A：异常验收矩阵

**执行日期：** 2026-09-21
**结果：** 9 项定向自动化检查全部通过；浏览器成功路径另见 `browser_acceptance/20260921T074342Z/`。

| 场景 | 预期边界 | 验收证据 | 结果 |
|---|---|---|---|
| 缺价 | 未知 SKU 返回 `missing_price`，不生成价格 | `MissingPriceTests.test_unknown_sku_rejected` | PASS |
| 无匹配 | 不可能的筛选返回空数组，不替换产品 | `SearchExampleTests.test_no_match_returns_empty_list` | PASS |
| 非法数量 | 0/负数等返回 `invalid_quantity` | `CanonicalContractTests.test_invalid_quantity_is_structured_error` | PASS |
| 超折扣 | 超过 500 bps 返回 `discount_limit_exceeded`，不截断 | `CanonicalContractTests.test_discount_limit_is_structured_error` | PASS |
| 模型超时 | 显式 Offline fallback，草稿金额和状态保留 | `AgentFailurePathTests.test_gateway_timeout_is_visible_and_falls_back_without_losing_quote` | PASS |
| 数据库失败 | 显示的草稿保留；恢复后相同请求可保存 | `QuoteApiTests.test_database_save_failure_preserves_draft_and_allows_retry` | PASS |
| PDF 失败 | confirmed snapshot 保持 exportable；恢复后可重试 | `QuoteApiTests.test_pdf_failure_preserves_confirmation_and_allows_retry` | PASS |
| 重复保存 | 精确重试返回原版本；不同元数据返回冲突 | `RepositoryLifecycleTests.test_save_is_idempotent_and_conflicting_customer_is_rejected` | PASS |
| 重复确认 | 精确重试返回同一 confirmation；不同确认信息被阻断 | `RepositoryLifecycleTests.test_confirmation_is_append_only_exactly_idempotent_and_exportable` | PASS |

执行命令使用临时 SQLite 数据库，运行结果为 `Ran 9 tests ... OK`。模型超时使用注入的 `TimeoutError` 验证本地失败恢复；组织者 Gateway 的真实限流/超时行为仍需在首次团队 API 运行中记录。
