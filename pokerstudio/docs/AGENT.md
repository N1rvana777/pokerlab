# Pokerstudio / Pokerlab 共用 agent

实现日期：2026-10-08。基础层位于 `pokerstudio/agent/`，没有嵌入剪辑或扑克计算；两入口使用同一经过校验的业务 callback，项目和分析会话使用独立 context。原 Pokerlab solver 仍通过自己的监督进程运行。

## 接入与实际协议

本机 `codex --version` 为 **codex-cli 0.162.0**。已读取 `codex app-server --help`，并用该二进制 `generate-json-schema --experimental` 导出了本机协议；没有升级 CLI。完整生成物是运行证据，位于忽略目录 `.data/protocol-schema/`。代码中的 `protocol-version.json` 保留所用契约，可执行 `python -m pokerstudio.agent.generate_protocol` 重新导出。

- stdio 传输为逐行 JSON；先 initialize（稳定应用名 pokerstudio、版本、experimentalApi=true），等待响应后发送 initialized。
- thread/start 的 dynamicTools 为 `{type:"function",name,description,inputSchema}`；不是旧示例中省略 type 的对象。
- 客户端接收 item/tool/call，参数按业务 schema 校验，然后执行 `execute_tool(name,args,context=...)`；返回 success 与 inputText 内容。业务错误返回 success=false 并显示，不能称为已完成编辑。
- SIWC下业务函数放入 pokerstudio namespace，满足当前ChatGPT plan usage的工具分组限制。若工具错误没有恢复，即使模型写出完成文字，应用最终状态仍为failed，并显示真实业务错误。
- 显示 item/agentMessage/delta；只有 turn/completed 且 turn.status=completed 算请求完成。interrupted 映射 cancelled，failed 保留错误。
- 取消发 turn/interrupt（threadId、turnId）；恢复使用保存的 threadId 与 thread/resume。会话不能隐式更换 provider、账号方式或项目。
- 禁用 shell、apps、plugins 与 web_search，关闭环境访问，设置只读沙箱。既有 CLI 的 MCP 配置表会合并，空表不能关闭继承工具；因此先通过正式 mcpServerStatus/list 发现名称，再重启本应用子进程，以进程级 mcp_servers.<name>.enabled=false 逐项禁用，同时在 thread 配置保留该限制。每次 turn 前再检查会话工具清单，若仍暴露外部 MCP 工具就拒绝推理。内置文件/shell/外部工具审批被拒绝。应用的可追踪业务工具负责所有修改，项目数据中的文字不会自动获得权限。
- analysis 入口不暴露剪辑编辑和导出工具；studio 入口不暴露独立分析配置修改。context.allowed_tools 可进一步收窄，两处都在实际 dispatch 前校验；恢复会话的工具 schema 摘要变化时必须新建会话。

动态工具仍属于官方实验接口。未来 CLI 升级需重新导出并复核 schema，不能假设保持兼容。CLI 的实验 chatgptAuthTokens 登录在本机 schema 明确标为内部使用，本应用不调用该接口。

## 本人订阅：默认正式 SIWC

首次启动的 `subscription` provider 选择 **Sign in with ChatGPT（siwc）**，遵循当前新接入推荐方式。本人显式选择其他模式后，应用保存该选择，重启不会强行改回 siwc：

1. 在应用 agent 设置中选择订阅，点击 Continue with ChatGPT（登录）。后端先启动 127.0.0.1 的独立 `/auth/callback` 监听器。
2. 浏览器打开返回的正式 OpenAI 授权 URL；第一次使用 dynamic_agent_client 动态注册、稳定 host ID、应用名 pokerstudio、PKCE S256、随机 state 与 nonce。用户在自己的账号中完成登录，并允许 ChatGPT plan usage。
3. 回调使用实际 issued client_id 交换授权码；cryptography 验证 JWKS 签名、issuer、audience、exp/iat/nbf、nonce 和账号身份。仅 identity 登录不足以推理，还必须包含 chatgpt.tokens.use.direct scope。
4. 应用自己的 OAuth 记录存于 `%LOCALAPPDATA%\Pokerstudio\agent\chatgpt.dpapi`，使用本人 Windows 用户范围的 DPAPI 加密。API key 和 OAuth 凭据不会写入剪辑项目、前端构建或日志。应用自己的 host ID 和 CLI 配置/会话目录也在该应用目录中。非 Windows 当前只保留内存凭据，尚无持久系统凭据存储适配器。
5. app-server 的独立 CODEX_HOME 使用该应用目录中的 codex-home。OAuth access token 只放入该子进程专用环境变量；按官方说明配置正式 `https://api.openai.com/v1` Responses provider。刷新成功后重启子进程并用 thread/resume 继续。没有读取、复制日常 CLI 的 auth.json、浏览器 cookie 或 token。

通过设置 `POKERSTUDIO_AUTH_HOME` 可以为本机另一位用户/账户安排独立目录；不要指向源码或剪辑项目目录。当前每个 auth_dir 保存一个选择的 SIWC 注册。扩展多个账户时应按 issued client_id + verified subject 分开记录，不能按 email 合并。

SIWC 模型选择使用当前账号的 `/v1/models` 目录，仍须完成真实 inference 才算验证所选模型可用。订阅额度错误、失败和登录超时会显示真实状态；不会自动切换为 API 计费。

**需要本人操作的步骤：**首次独立 SIWC 授权只能由用户在正式页面完成。开发者不能代用户同意 plan usage 或操作登录凭证。在没有完成该授权前，应用默认订阅方式标为尚未登录，不会把按钮和协议测试视作接通。

## 可选：既有 CLI 登录 / 隔离 managed 登录

为本机个人使用及验收保留两种显式模式：

- `existing_cli`：app-server 通过正式 account/read 查看既有 CLI 登录。只有 account.type=chatgpt 才允许订阅请求；apiKey/Bedrock 登录明确拒绝。使用 CLI 原有认证生命周期，不改日常 config.toml、不读 token。新建的是本应用会话，不接管或覆盖已有会话；CLI 自身会创建运行缓存和新会话记录。应用不提供注销日常账号操作。
- `managed`：隔离 CODEX_HOME 中调用正式 account/login/start type=chatgpt（或 device-code）。登录、持久凭据和刷新全部由 Codex 管理；不覆盖日常配置。

当前官方文档允许继续既有本地/开源 app-server authentication，并推荐迁移 SIWC。新安装默认 SIWC，managed/existing_cli 用于本人本机兼容；不是商业或共享托管认证架构。未来远程收费产品使用正式 API 或当时认可的商业 SIWC 接入。

## API 模式

明确选择 `api` provider，后端 configure_api 接收 API key、模型、allow_paid。key **只保留在后端内存**，重启后需重新提供；不保存到 sessions.json 或项目文件。只有用户明确开启 allow_paid=true 后才允许 inference。模型列表查询不证明模型有推理权限，真实成功完成才进入 verified_models。

使用正式 POST `/v1/responses` 的 HTTP/SSE，store=false、stream=true；应用保持必要文字/工具历史，串行 dispatch 校验后的 function calls。只有 response.completed 算请求完成，半截流、response.failed/incomplete、认证/限额和取消不会算成功。失败后可用原 session_id 明确重试，网络层不自动重复付费请求。

界面必须显示 “OpenAI API 独立计费”。订阅与 API 不会静默互换。API 真实验收当前等待用户配置凭据及明确付费授权。

音视频转写、配音、生成和媒体上传是独立能力。SIWC plan usage 当前不支持原始音视频输入、Files上传API或transcription API；本应用使用本地FFmpeg/字幕/solver，agent只接收必要的文字和结构化业务数据。没有自动使用收费转写。

## 后端接口

```python
AgentService(data_dir, execute_tool, tool_schemas, workspace=None, auth_dir=None)
# tool_schemas = [{"name": ..., "description": ..., "input_schema": {...}}]
# execute_tool(name, args, context=None) -> JSON-compatible business result

service.status(provider=None)
service.configure_subscription(mode="siwc")  # siwc / managed / existing_cli
service.login(provider="subscription", mode=None)
service.cancel_login(login_id=None)
service.models(provider="subscription")
service.configure_api(api_key, model, allow_paid=False)
service.start(message, provider="subscription", model=None, session_id=None, context=None)
service.get(task_id, after=0)
service.cancel(task_id)
service.list_sessions(context=None)
service.close()
```

start 立即返回 task/session ID，界面用 get 的 cursor 拉取新增 delta/tool_call/tool_result/usage/终态事件。每个工具结果带 success，后台媒体/求解工具返回 queued/running 时须继续查询任务；助手不能把“任务创建”解释为成片或数值已完成。全局串行 agent turn 保持项目变更顺序；业务层还检查项目身份、校验输入、保存审计与撤销。

## 验证与恢复

```powershell
# 仓库根目录 C:\Users\n1rva\projects\pokerlab
python -m pytest pokerstudio/tests/test_agent.py pokerstudio/tests/test_agent_auth.py -q
python -X utf8 -m pokerstudio.agent.check_cli --existing-cli
python -X utf8 -m pokerstudio.agent.acceptance --mode existing_cli --solver
```

验收脚本使用真实 Studio 业务工具创建 **TEST ONLY** 隔离项目，通过自然语言修改底池/字幕、保存重开，再在独立分析 context 调用真实 solver 并读取报告。记录位于 `.data/agent-acceptance/<时间戳>/acceptance.json`。该命令会消费本人订阅额度，但不会消费API额度。在受限开发沙箱内，Codex运行缓存/网络以及WSL可能需正常权限审批。

截至2026-10-08，15项针对性单元测试通过，覆盖流式EOF、失败工具结果、取消、会话及设置恢复、入口与工具范围隔离、API费用授权、OIDC签名和nonce/state、DPAPI保护；这些测试验证实现契约，真实接通证据如下。

- 通过正常权限运行 check_cli，正式 account/read 确认既有 CLI 为 ChatGPT Pro；模型候选默认 gpt-6.1-sol。关闭继承 MCP 后，进程和临时会话均报告 external_mcp_tool_count=0（保留2个已关闭的配置名称）。没有读取日常凭据文件。
- 首次真实验收 `.data/agent-acceptance/1791502475/acceptance.json` 为 passed:true。隔离修复后再次运行，最新证据 `.data/agent-acceptance/1791503042/acceptance.json` 同样为 passed:true，两个真实请求均记录 external_mcp_tool_count=0。
- 剪辑入口真实调用 read_project、update_hand、update_subtitle；底池改为120，0–2秒测试字幕保存，使用新的 ProjectStore 重开确认。未知底牌仍为空，修改审计来源为agent。
- 独立分析真实调用 read_project、solve_hand、get_task、get_solver_result。任务成功并回收原生进程；报告根EV为13.3332891464与6.6667108536筹码，exploitability为0.00932455063筹码，即底池0.0466227531%，达到该测试局面的0.05%目标。报告明确均衡基线命中缓存（原基线530迭代）；本次不是新的冷启动均衡计算。
- 本轮真实登录路径为本人 existing_cli。独立 SIWC 与 managed 首次登录仍需要本人完成正式授权页面；API没有配置、没有计费调用，实际API接通仍未验证。

早期沙箱检查保留的具体失败为 `Error: Access is denied. (os error 5)`，伴随 `.codex/tmp/arg0` 缓存创建拒绝；正常权限下后续检查已成功。隔离调试也确认 `mcp_servers={}` 不足以关闭继承工具，已用逐项进程覆盖修复。后续实测以验收JSON与PROGRESS为准。

应用自己的 agent-settings.json 保存 subscription_mode 与最多100条历史模型成功摘要，不改日常全局配置。status 的 historical_model_validations 标明曾完成请求的模型、时间和会话；这不是当前账号权限或剩余额度保证。verified_models 只表示当前应用进程的成功请求，重启或切换模式后重新验证。API key 与 allow_paid 均不保存，重启必须重新配置并授权。

恢复应用后打开相同项目、相同入口和 provider，使用保存的 session_id 继续。保存的 thread_id 与最近 turn_id 用于恢复并过滤前一轮迟到事件；API 保存必要文字和工具历史，使用 store=false 重放。若切换项目、账号方式、provider、工具定义或应用登录目录，创建新会话。请求失败保留真实error；不要将部分文字或queued任务视作成功。损坏的会话或设置原文件保留，新记录写入独立恢复文件。

## 当前官方依据（实际阅读于2026-10-08）

- [Codex App Server：协议、动态工具、认证与新接入建议](https://learn.chatgpt.com/docs/app-server)
- [ChatGPT plan usage：本地客户端及稳定host标识](https://developers.openai.com/siwc/token-sharing-open-source)
- [SIWC注册、PKCE、回调、ID token及权限校验](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
- [SIWC与Codex app-server：正式Responses provider配置](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server)
- [SIWC当前限制](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)
- [SIWC模型目录与完成事件](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
- [Responses创建参数](https://developers.openai.com/api/reference/resources/responses/methods/create)
- [Responses流式事件](https://developers.openai.com/api/reference/resources/responses/streaming-events)
- [Codex配置参考：MCP、apps与工具开关](https://learn.chatgpt.com/docs/config-file/config-reference)
