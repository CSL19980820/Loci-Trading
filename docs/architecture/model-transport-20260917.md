# 模型通信：HTTP/2 与 gRPC

## 当前生产状态（2026-09-17 23:55 验收）

业务模型请求已启用全量gRPC路由：`LOCI_LLM_GRPC_MODE=all`、`LOCI_GRPC_MULTI_TENANT=1`；网关使用与租户绑定的凭据解析该租户配置，不再局限于最初的单租户单供应商试用。当前镜像为 `loci-qianlong:2.0.0-20260917-leader-watch5`。请求提交前的HTTP兼容回退保留，提交后不因换协议重放。

本轮真实流式验收：B.AI与GLM均通过gRPC返回200和正文OK；deepseek配置返回上游401，独立HTTP直连也返回401，尚需修正该供应商的API Key，不计为成功调用。原报告链接的文件权限问题已修复，浏览器及HTTP请求均确认200。

后续发布、5只非持仓观察池、验证范围、回滚与剩余事项见 `leader-watch5-20260917.md`。以下保留首次HTTP/2与可选gRPC发布时的实施记录，不代表当前仍只启用单供应商链路。

## 首次发布：HTTP兼容链路

统一模型客户端的同步、异步流式请求，以及 MCP HTTP 客户端，均启用 `http1=True, http2=True`。支持 HTTP/2 的服务通过协商使用 HTTP/2；仅支持 HTTP/1.1 的服务继续使用 HTTP/1.1。保留 JSON 请求、SSE 回复、供应商代理和证书校验。Nginx 对外 HTTPS 支持 HTTP/2，Nginx 到 Uvicorn 的回源仍为 HTTP/1.1。

`LOCI_HTTP2=0` 可强制上述出站客户端使用 HTTP/1.1。生产 `.env` 修改后须重新创建容器使环境变量生效。自动兼容是连接协商，不是在已提交模型请求后盲目重试。

Agent 生命周期内通过 `client_session.py` 复用客户端。不同线程、租户、供应商、凭据和传输方式隔离，运行结束关闭；异步连接绑定原事件循环。

## gRPC 的边界

新增的是 **Loci 客户端 → Loci 模型网关** 的真实 gRPC 服务，协议定义为 `src/ai/infrastructure/grpc_wire.proto`。网关再请求已配置的模型供应商，优先 HTTP/2。

Protobuf 定义供应商引用、请求信封和响应流帧；供应商原生 JSON 与 SSE 字节保留在信封中。它不是第三方供应商的原生 gRPC API，也不是把整个模型消息结构改成 Protobuf。额外网关可能增加开销，不能宣称天然更快。

网关从自己的固定租户配置中解析供应商 URL、模型和密钥；客户端不传供应商 URL 或供应商密钥，不能选择其他租户。模型网关不执行工具或交易。

## 服务端配置

| 变量 | 含义 |
|---|---|
| `LOCI_GRPC_LISTEN` | 例如 `127.0.0.1:50051`；不配置则不启动 |
| `LOCI_GRPC_TENANT` | 网关固定租户，默认 `__primary__` |
| `LOCI_GRPC_TOKEN` | 至少 32 字符的 ASCII 访问令牌，使用安全随机值 |
| `LOCI_GRPC_CERT` / `LOCI_GRPC_KEY` | 服务端 TLS 证书和私钥路径；非回环监听必须使用 TLS |

可以通过应用 lifespan 随服务启动，也可以执行 `python -m src.ai.infrastructure.grpc_gateway` 独立启动。当前生产网关仅监听容器内部回环地址，不映射公网端口。

## 可选客户端路由

默认业务继续直连供应商，不自动切换到 gRPC。以下变量同时匹配当前租户与供应商名称时，`resolve_config` 才选择网关：

| 变量 | 含义 |
|---|---|
| `LOCI_LLM_GRPC_TENANT` | 精确匹配租户 |
| `LOCI_LLM_GRPC_PROVIDER` | 精确匹配供应商名称 |
| `LOCI_LLM_GRPC_ENDPOINT` | `http://127.0.0.1:50051` 或远程 `https://host:port` |
| `LOCI_LLM_GRPC_TOKEN` | 对应服务端访问令牌 |
| `LOCI_LLM_GRPC_CA` | 可选的受信任 CA 文件；不关闭证书校验 |
| `LOCI_LLM_GRPC_FALLBACK` | `1` 允许请求提交前的网关健康检查失败时走原 HTTP；默认关闭 |

程序内也可通过 `ProviderConfig` 的 `grpc_endpoint`、`grpc_token`、`grpc_ca_file`、`grpc_fallback` 选择链路。网关自身解析配置时禁用 gRPC 路由，避免递归转发。

## 失败与取消

`Check` 只检查鉴权和供应商配置，不发起模型推理。仅其 `UNAVAILABLE` / `DEADLINE_EXCEEDED` 在显式允许时回退原 HTTP。鉴权失败、供应商配置不匹配不回退。

`Exchange` 一旦提交，传输错误、超时、已开始的流失败均不因切换协议而重放。gRPC SDK 重试被禁用，Agent 识别 `LLMNoReplayError`。异步取消关闭上游请求，避免模型读取线程遗留。原有明确的模型业务恢复逻辑与传输层重试是不同概念。

当前单条消息上限 32 MiB，响应字节按至多 64 KiB 分帧，网关最多 16 个并发 RPC。明文 gRPC 只允许回环地址；远程链路需要 TLS。

## 可观测性与验证

日志记录 `upstream_http` 的 host、HTTP 版本、状态码、transport 和 gateway_upstream，不记录认证头、令牌、完整请求体。

2026-09-17 21:49，北京时间，在正式容器对当前 `B.AI · 守护 / deepseek-v4.1-flash` 执行真实流式请求：

| 路由 | 实际版本 | 结果 | 整次耗时 |
|---|---|---|---|
| 强制 HTTP/1.1 | HTTP/1.1 | 200，正文 `OK` | 2044 ms |
| HTTP/2 优先 | HTTP/2 | 200，正文 `OK` | 3740 ms |
| gRPC 网关 | gRPC/HTTP2，网关上游 HTTP/2 | 200，正文 `OK` | 1477 ms |

以上每条仅一个样本，输出 token 数也不同，只能证明真实协议和流式功能可用，不能据此排名性能或计算加速比例。

测试入口：

```sh
python -m pytest tests/ai tests/intel tests/ledger/test_stock_agent_store.py tests/ledger/test_stock_agent_zero_limits.py -q
python -m ruff check --select F src cli tests
python tools/import_smoke.py
```

新增真实 socket 测试覆盖 TLS/ALPN HTTP2、HTTP1.1 协商、强制回退、SSE、连接复用、gRPC 双协议工具多轮、鉴权失败、证书验证、请求前回退、提交后故障不重放、取消与截止时间。模拟故障只用于明确的网络异常注入，正常协议测试使用真实服务器与真实连接。

协议文件变更后，用锁定的开发依赖 `grpcio-tools==1.84.0` 重新生成：

```sh
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. src/ai/infrastructure/grpc_wire.proto
python -m ruff check --select F --fix src/ai/infrastructure/grpc_wire_pb2_grpc.py
```

## 20:00 复盘故障

2026-09-17 龙头选手在 20:00:00 启动，20:13:39 提交失败，错误为“账户超出智能体数量约束”。生产配置的 `daily_selection_limit=0` 表示不设上限，但旧存储层把已有 9 条当日选择记录与零直接比较，拒绝了整个事务。仓库已有的修正尚未部署。

此次发布补齐存储层条件：只有配置值为正时才比较数量，保留账户守恒、持仓、交易日和交易阶段校验。新增回归覆盖无限额、正上限越界、正上限内三种情况，并验证复盘不改变现金和成交。

原失败记录 `eb40c5b4328d4b10abb87837db5c37e6` 保留。补跑使用独立 recovery slot，不删除原始失败、不重放原交易。

补跑 `5abfd3ee825943cfb47453ef5e5cf1a0` 于北京时间 2026-09-17 21:50:13 启动、21:52:00 完成。独立只读 SQLite 检查确认：`status=success`、`fills=0`、该运行的成交记录数为 0；企微通知回执 `success=true`、`sent=["wecom"]`，通知错误数 0。补跑期间六次模型响应均为 HTTP/2、状态 200。

临时验证脚本在成功提交、发送通知之后，误用持仓字段 `shares` 报错；现金一致性断言此前已通过。最终以另一个只读校验确认成功状态、通知回执和零成交，未重跑成功任务、未重复发送通知。

验证汇总：AI 与账本回归 375 项通过；情报/MCP 回归 169 项、5 个子测试通过；实际发布包测试 24 项通过；`ruff --select F src cli tests` 通过；679 个模块导入冒烟，0 失败。生产容器健康，Nginx 配置检查通过，公网健康接口返回 200 并协商为 HTTP/2。

独立容量风险：服务器根分区约 40 GB，初次验收仅剩约 274 MB，最终检查剩余约 338 MB。镜像导出曾因空间不足失败，残缺导出包已删除；最终通过摘要校验后直接复用已构建镜像完成发布。该容量风险未被此次功能修复消除，未执行历史数据或 Docker 产物的批量清理。

本次清理已核验：本地 `.local/transport-20260917/`、服务器上传压缩包、两个临时验证脚本及发布目录内的隔离测试数据副本均已删除。保留生产发布源、镜像、摘要清单和回滚备份；未删除生产 `/srv/qianlong-loci/data`。最终生产镜像仍为本次发布版本，容器状态 `healthy`。

## 发布范围

生产镜像：`loci-qianlong:2.0.0-20260917-http2-grpc`，镜像 ID `sha256:427c40a0b62162a1dcb704599f5350013f598249de964d1491973c705c28aacd`。

以此前正式镜像的源码为基底，定向纳入 17 个通信、装配和存储相关文件。未发布工作区其他前端或业务改动。发布使用既有健康检查、Nginx 校验和回滚流程；发布副本增加已验证镜像摘要复用分支，避免服务器重复下载或导出镜像。
