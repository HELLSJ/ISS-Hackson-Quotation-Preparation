# 组织者 LLM Gateway 配置指南

项目已切换到组织者提供的 LLM API Gateway。模型负责理解语言和发起工具请求；产品事实和报价金额仍由本地三个确定性工具计算。

## 1. 准备三个值

从组织者发给团队成员的最新邮件中取得：

- API URL；
- 团队 API key；
- 可用的 model 名称。

不要把真实 API key 写进仓库、Markdown、`.env.example`、命令行参数、截图或评测报告。

## 2. 在当前终端安全配置

在项目根目录执行：

```bash
read -r "LLM_GATEWAY_URL?Gateway URL: "
read -s "LLM_GATEWAY_API_KEY?Team API key: "; echo
read -r "LLM_MODEL?Model name: "
export LLM_GATEWAY_URL LLM_GATEWAY_API_KEY LLM_MODEL
export AGENT_DRIVER=gateway
```

`read -s` 输入时终端不会显示 API key。新建终端后这些环境变量会消失，需要重新配置。不要把 key 写进 `~/.zshrc`；如确需长期保存，应使用团队批准的密码管理或 Secret Manager。

只检查变量是否存在，不打印内容：

```bash
for name in LLM_GATEWAY_URL LLM_GATEWAY_API_KEY LLM_MODEL; do
  if [[ -n ${(P)name} ]]; then echo "$name: configured"; else echo "$name: missing"; fi
done
```

## 3. 运行本地连通性检查

下面的命令使用项目的 Gateway client，不会显示 API key：

```bash
.venv/bin/python scripts/check_llm_gateway.py
```

成功时会输出协议、模型名和响应状态。失败时只输出经过清理的错误类型或 HTTP 状态码。

URL 规则：

- 普通 Gateway 根地址自动调用 `/api/chat`，使用 `X-API-Key`；
- 以 `/api/chat` 结尾的 URL 直接使用；
- 以 `/v1` 或 `/chat/completions` 结尾的地址按 OpenAI 兼容协议调用。

## 4. 启动应用

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 <http://127.0.0.1:8000>。健康接口应显示：

```json
{
  "configured_driver": "gateway",
  "gateway_configured": true
}
```

发起对话后，真实 Gateway 成功的判定条件是：

- `configured_driver` 为 `gateway`；
- `used_fallback` 为 `false`；
- trace 包含 `gateway_start` 和带 `tool` 的 `gateway_turn_*`；
- 报价金额来自 `calculate_quote` 的结果。

如果 Gateway 不可用，应用会显式写入 `gateway_fallback` 并使用 OfflineDriver 保留可用流程。这种结果不能记作真实模型成功。

## 5. 运行正式评测

先确认 sealed holdout 已由非作者完成审核，然后运行：

```bash
.venv/bin/python scripts/run_formal_evaluation.py \
  --driver gateway \
  --label first-pass
```

运行器从环境变量读取 URL、API key 和 model。报告只保存 URL 的 SHA-256，不保存 URL 原文或 API key。

效率计时：

```bash
.venv/bin/python scripts/run_efficiency_timing.py \
  --driver gateway \
  --label first-pass
```

首次正式结果应原样保留；修复后使用新的 label，避免覆盖首轮证据。

## 6. 常见问题

### `gateway_configured: false`

至少一个环境变量缺失。回到第 2 步，并确保启动 Uvicorn 的同一个终端拥有这些变量。

### `Gateway HTTP 401` 或 `403`

检查 URL 和团队 API key 是否来自最新邮件、是否过期，以及是否复制了多余空格。不要在终端输出完整 key。

### `Gateway HTTP 429`

可能达到速率或额度限制。客户端会有限重试一次；继续失败时会显式 fallback。检查团队共享额度后再运行批量评测。

### 模型返回 JSON 工具请求

这是受支持的兼容路径。客户端会解析 `{"tool":"...","args":{...}}`，在本地执行工具，再把结果发回 Gateway。

### AWS Console 显示模型权限错误

这不影响当前推理路径。项目不再直接调用 Bedrock；AWS 账户只用于 Lightsail 托管。
