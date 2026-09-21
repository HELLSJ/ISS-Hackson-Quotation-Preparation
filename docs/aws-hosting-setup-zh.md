# AWS Lightsail 托管配置

本项目的模型推理使用组织者提供的 LLM API Gateway。AWS 账户只用于部署和运行 Web 应用，例如 Lightsail；应用本地运行和 Gateway 推理都不需要 AWS Access Key。

## 两类身份的用途

| 配置 | 用途 | 是否用于模型推理 |
|---|---|---|
| 组织者 Gateway URL + API key | 调用团队共享的 LLM 服务 | 是 |
| AWS Console / Lightsail SSH | 创建、登录和维护 Ubuntu 实例 | 否 |
| 本地 AWS CLI Profile | 用 CLI 管理有权限的 AWS 资源 | 否 |

浏览器里的 **Connect using SSH** 只会建立到 Lightsail Ubuntu 的终端连接。它不会给本地程序提供 LLM API key，也不会让应用直接调用模型服务。

## 推荐部署流程

1. 在 Lightsail 创建或使用现有 Ubuntu 实例。
2. 通过控制台 SSH 或自己的 SSH 客户端登录。
3. 在实例上克隆仓库并创建虚拟环境。
4. 在实例的服务环境中配置 `LLM_GATEWAY_URL`、`LLM_GATEWAY_API_KEY`、`LLM_MODEL` 和 `AGENT_DRIVER=gateway`。
5. 用 systemd 或其他进程管理器启动 Uvicorn。
6. 只开放应用需要的端口，并为公开访问配置反向代理和 HTTPS。

Gateway 配置、连通性检查和正式评测命令见 [LLM Gateway 配置指南](llm-gateway-setup-zh.md)。

## 本地 AWS CLI Profile（仅在需要管理托管资源时）

如果团队要求使用 AWS CLI，可以通过 SSO 建立 Profile：

```bash
aws configure sso --profile showme-hosting
aws sso login --profile showme-hosting
AWS_PROFILE=showme-hosting aws sts get-caller-identity
```

临时 Access Key 也可以保存到单独 Profile，但不要提交 `~/.aws/credentials`、不要写入项目 `.env`，也不要把凭据贴进聊天、截图或日志。临时凭据过期后需要重新获取。

应用推理代码不会读取 `AWS_ACCESS_KEY_ID`、`AWS_SECRET_ACCESS_KEY`、`AWS_SESSION_TOKEN`、Bedrock API key 或 AWS Region。

## 清理旧推理凭据

如果此前为了直接模型调用创建了长期 Bedrock API key，请在确认无人继续使用后到 AWS 控制台停用并删除。它不再是本项目依赖。当前终端可清除旧变量：

```bash
unset AWS_BEARER_TOKEN_BEDROCK BEDROCK_MODEL_ID
```

用于 Lightsail 管理的 SSO Profile 可以保留；不要删除仍在使用的实例或托管身份。
