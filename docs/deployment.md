# 潜龙记忆宫殿部署指南

本文是给服务器维护者的操作指南。生产账本以服务器的 SQLite 文件为唯一事实源；本地数据库只用于离线测试或首次迁移。

## 部署边界

| 内容 | 位置 | 后续同步是否覆盖 |
|---|---|:---:|
| SQLite 账本（含 WAL/SHM） | `/srv/qianlong-palace/data/` | 否 |
| 生产环境变量、写入令牌与应用登录会话密钥 | `/srv/qianlong-palace/.env` | 否 |
| 每次发布的代码与 Vue `dist` | `/srv/qianlong-palace/releases/<release>` | 是，新增版本 |
| 当前生效版本软链接 | `/srv/qianlong-palace/current` | 是，健康检查通过后切换 |

容器只监听 `127.0.0.1:18787`。外网流量必须先经过 Nginx；不要将 Uvicorn 端口直接暴露到公网。

首次迁移完成后，Agent 与工作台都应写入服务器 API 对应的账本。同步脚本只发布代码和前端产物，不会合并、更换或从本地覆盖服务器 SQLite；日后的 `-InitializeData` 也会因远端数据库已存在而跳过。

## 前置条件

- Debian 服务器已安装 Docker Engine 与 Docker Compose v2。
- DNS 为目标域名配置 A/AAAA 记录，例如 `qianlong.chenkit.cloud` 指向服务器公网 IP。
- 推荐：已为该域名签发 TLS 证书，以 HTTPS 对公网提供服务。
- 临时：若明确启用 HTTP 风险模式，则只能用于你可控的短期排障；HTTP 不加密，登录密码、会话 Cookie、写入令牌和账本内容可能被网络中的第三方截获或篡改，不能作为公网长期运行方案。
- Nginx 已在服务器运行。当前机器使用的是 `/home/software/nginx/sbin/nginx`，不要覆盖 `/home/software/nginx/conf/nginx.conf` 或现有站点。
- 本机已配置 `ssh my-debian`，并安装 OpenSSH 客户端、Node.js 与 npm。

`PALACE_ALLOWED_HOSTS` 填对外主机名，不带协议、路径或端口。例如：`qianlong.chenkit.cloud`。容器健康检查会以此列表的第一个域名作为 `Host` 请求本机 API，不扩大生产 Host 白名单。

## 首次安装

先以 `root`（或有等效目录和 Docker 权限的用户）登录服务器，创建数据与配置边界：

```bash
install -d -m 0750 /srv/qianlong-palace
install -d -m 0750 /srv/qianlong-palace/releases
install -d -m 0750 /srv/qianlong-palace/.staging
install -d -o 10001 -g 10001 -m 0750 /srv/qianlong-palace/data
umask 077
nano /srv/qianlong-palace/.env
chmod 600 /srv/qianlong-palace/.env
```

把下列真实值写入 `/srv/qianlong-palace/.env`。不要把这个文件放进仓库、聊天记录或同步目录。

```dotenv
PALACE_ALLOWED_HOSTS=qianlong.chenkit.cloud
PALACE_WRITE_TOKEN=替换为openssl-rand-hex-32生成的随机值
PALACE_AUTH_USERNAME=admin
PALACE_AUTH_PASSWORD=由服务器维护者预先设置的固定密码
PALACE_SESSION_SECRET=替换为openssl-rand-hex-32生成的随机值
```

`PALACE_INSECURE_HTTP` 是可选项，默认不设。不设时会话 Cookie 带 `Secure` 标记，只经 HTTPS 回传，这是推荐状态。仅当使用下文的 HTTP 临时模式时才需要置 `1`，否则浏览器不会回传 Cookie，表现为“登录成功但立刻被踢回登录页”。`-ConfigureNginx` 会校验这个值与协议模式一致，不一致直接终止部署。

在服务器上生成写入令牌的真实命令：

```bash
openssl rand -hex 32
```

首次发布前，在本机工作区执行预览。它会构建前端并创建临时发布包，但不会连接服务器：

```powershell
rtk pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\sync-to-server.ps1
```

`-InitializeData` 会先用 Python `sqlite3.backup()` 为本地 `.palace/qianlong.db` 生成一致性快照；它只会在服务器还没有 `/srv/qianlong-palace/data/qianlong.db` 时导入该快照，已存在时必定跳过，绝不覆盖。

脚本上传的白名单只有 `requirements.txt`、`src/`、`frontend/dist/` 与运行所需的 `deploy/` 文件。因此不会上传 `node_modules`、`.palace/`、`.env`、SSH 凭据或其他工作区文件。Docker 在服务器上只使用上传的 Vue 构建产物，不安装 Node.js。

## 自动配置 Nginx：HTTP 临时模式

> 警告：HTTP 不提供传输加密。即使应用登录会话有效期为 30 天，Cookie 本身仍会明文传输；请仅用于短期确认服务链路，随后切换到 HTTPS。

脚本可将 [HTTP 独立模板](../deploy/nginx-qianlong-palace-http.conf.template) 渲染到服务器的 `/home/software/nginx/conf/conf.d/qianlong-palace.conf`，建立唯一映射：

```text
http://qianlong.chenkit.cloud:80 → Nginx → 127.0.0.1:18787
```

它不复用或改写旧的 `sub2api.chenkit.cloud` 路由，也不暴露 `18787` 公网端口。必须显式携带 `-AllowInsecureHttp`，并且仅能与 `-ConfigureNginx -Deploy` 或 `-ConfigureNginx -DryRun` 一同使用；不能传入 TLS 或 Nginx Basic Auth 参数。

HTTP 模式的 Nginx 不保存、生成或轮换任何密码。登录由应用的单账号会话负责：账号固定为 `admin`，会话有效期为 30 天。密码与会话密钥均只保存在发布目录外的 `/srv/qianlong-palace/.env`；日后的同步不会覆盖该文件，因此不会影响已登录状态或更改密码。

自动配置前必须完成以下前置条件：

- DNS 已将 `qianlong.chenkit.cloud` 指向该服务器，且 `/srv/qianlong-palace/.env` 内 `PALACE_ALLOWED_HOSTS` 的第一个域名与它完全一致。
- `/srv/qianlong-palace/.env` 已预先配置固定账号 `PALACE_AUTH_USERNAME=admin`、固定 `PALACE_AUTH_PASSWORD` 与 `PALACE_SESSION_SECRET`。同步脚本绝不生成、替换或轮换这些值。
- `/srv/qianlong-palace/.env` 已设置 `PALACE_INSECURE_HTTP=1`。HTTP 模式下会话 Cookie 必须去掉 `Secure` 标记，否则浏览器不回传 Cookie，登录无法保持。切回 HTTPS 时必须删除该行或置 `0`，脚本会校验，不一致即终止。

当前服务器使用自定义 Nginx 二进制。自动配置会先确认主配置包含 `conf.d/*.conf`，不会替换 `/home/software/nginx/conf/nginx.conf` 或其他站点；若当前 Nginx 不包含该目录，脚本会失败而不写入。

确认前置条件后，首次发布、迁移账本并自动加载 HTTP 映射：

```powershell
rtk pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\sync-to-server.ps1 `
  -Deploy -InitializeData -ConfigureNginx -AllowInsecureHttp `
  -Domain qianlong.chenkit.cloud
```

`-Domain` 只能是 FQDN。脚本不会修改 `.env`，而是在远端校验 `PALACE_ALLOWED_HOSTS` 首域名是否与 `-Domain` 一致；不一致、缺登录环境变量或 Nginx 校验失败都会终止部署。模板只监听 `80`，请求体限制为 `64k`，并向应用透传 `Host`、来源 IP 与转发协议头。写入前会备份自己的独立 Nginx 配置，执行 `nginx -t`；校验或 reload 失败则恢复备份并 reload 恢复后的配置。

## 自动配置 Nginx：HTTPS（推荐）

获得证书后，使用 [HTTPS 独立模板](../deploy/nginx-qianlong-palace.conf.template) 替换 HTTP 配置。HTTPS 模式仍需服务器上的 Basic Auth 文件；该文件由服务器维护者预先创建并保存在发布目录外，同步脚本只校验与引用，绝不写入、替换或轮换。

```powershell
rtk pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\sync-to-server.ps1 `
  -Deploy -ConfigureNginx `
  -Domain qianlong.chenkit.cloud `
  -TlsCertPath /etc/letsencrypt/live/qianlong.chenkit.cloud/fullchain.pem `
  -TlsKeyPath /etc/letsencrypt/live/qianlong.chenkit.cloud/privkey.pem `
  -BasicAuthFile /home/software/nginx/conf/.qianlong-palace.htpasswd
```

## 日后同步

用户说“同步”时，在本机执行：

```powershell
rtk pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\sync-to-server.ps1 -Deploy
```

脚本会先跑 `pytest tests/`，不过不打包；随后执行 `npm run build`，上传临时 staging 包，在服务器上做 Compose 配置校验、构建镜像并等待健康检查。仅健康检查通过才把 `current` 指向新版本。构建或健康检查失败时，旧版本保持为当前版本；若新容器失败，脚本会尝试恢复旧版本容器。

发布前测试依赖 `pytest`，安装方式：

```bash
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
```

确有必要时可用 `-SkipTests` 跳过，脚本会打印警告。这是逃生口，不是常规用法。

日常代码同步不需要再次修改 Nginx。仅在域名、协议模式、证书、私钥或 Basic Auth 文件路径变动时，重新携带完整的 `-ConfigureNginx` 参数；脚本会覆盖自己的独立 `server` 文件并保留带时间戳的上一份备份。

如已在其他流程中构建好 `frontend/dist`，可以跳过本地构建：

```powershell
rtk pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\sync-to-server.ps1 -Deploy -SkipFrontendBuild
```

显式预览可加 `-DryRun`。无论是否附加其他参数，它都不会 SSH 连接或修改服务器。预览 HTTP 映射时使用与部署相同的显式风险参数：

```powershell
rtk pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\sync-to-server.ps1 `
  -DryRun -ConfigureNginx -AllowInsecureHttp `
  -Domain qianlong.chenkit.cloud
```

## 运行检查、备份与恢复

运行检查：

```bash
docker compose --env-file /srv/qianlong-palace/.env -f /srv/qianlong-palace/current/deploy/docker-compose.yml ps
curl --fail -H 'Host: qianlong.chenkit.cloud' http://127.0.0.1:18787/api/health
```

将命令中的 `qianlong.chenkit.cloud` 替换成 `.env` 内 `PALACE_ALLOWED_HOSTS` 的第一个域名。

备份必须使用 SQLite 的在线备份接口，避免直接复制处于写入中的 `qianlong.db`。每天或每次重大录入后执行：

```bash
install -d -m 0700 /srv/qianlong-palace/backups
sqlite3 /srv/qianlong-palace/data/qianlong.db ".backup '/srv/qianlong-palace/backups/qianlong-$(date +%F-%H%M%S).db'"
sha256sum /srv/qianlong-palace/backups/qianlong-*.db | tail -n 1
```

恢复前先停止服务并保留当前数据库副本，再替换数据库：

```bash
docker compose --env-file /srv/qianlong-palace/.env -f /srv/qianlong-palace/current/deploy/docker-compose.yml stop
cp -a /srv/qianlong-palace/data/qianlong.db /srv/qianlong-palace/data/qianlong.before-restore.db
install -o 10001 -g 10001 -m 0600 /srv/qianlong-palace/backups/要恢复的备份.db /srv/qianlong-palace/data/qianlong.db
rm -f /srv/qianlong-palace/data/qianlong.db-wal /srv/qianlong-palace/data/qianlong.db-shm
docker compose --env-file /srv/qianlong-palace/.env -f /srv/qianlong-palace/current/deploy/docker-compose.yml up -d
```

恢复命令中的 `要恢复的备份.db` 必须替换为已验证的实际文件名。恢复操作会改变生产账本，执行前先确认备份时间点。

## 代码回滚

发布目录不会被同步脚本删除。先查看可用版本：

```bash
ls -1dt /srv/qianlong-palace/releases/*
```

选择一个已知可用版本后，以该目录启动并切换软链接：

```bash
previous=/srv/qianlong-palace/releases/release-替换为目标版本
docker compose --env-file /srv/qianlong-palace/.env -f "$previous/deploy/docker-compose.yml" up -d --build --remove-orphans
ln -sfn "$previous" /srv/qianlong-palace/current
```

代码回滚不接触 `/srv/qianlong-palace/data/`，因此不会倒退账本数据。
