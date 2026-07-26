[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]*$')]
    [string]$Server = 'my-debian',

    [ValidatePattern('^/[A-Za-z0-9._/-]+$')]
    [string]$RemoteRoot = '/srv/qianlong-palace',

    [switch]$Deploy,
    [switch]$DryRun,
    [switch]$InitializeData,
    [switch]$SkipFrontendBuild,
    [switch]$SkipTests,

    [switch]$ConfigureNginx,
    [switch]$AllowInsecureHttp,
    [string]$Domain = '',
    [string]$TlsCertPath = '',
    [string]$TlsKeyPath = '',
    [string]$BasicAuthFile = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($RemoteRoot -match '(^|/)\.{1,2}(/|$)') {
    throw 'RemoteRoot 不允许包含 . 或 .. 路径段。'
}

function Test-SafeLinuxAbsolutePath {
    param([string]$Value)

    return $Value -match '^/[A-Za-z0-9._/-]+$' -and
        $Value -notmatch '(^|/)\.{1,2}(/|$)' -and
        -not $Value.Contains('//')
}

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory)] [string]$FilePath,
        [Parameter(Mandatory)] [string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "命令失败（exit=$LASTEXITCODE）：$FilePath $($Arguments -join ' ')"
    }
}

$requestedDeploy = [bool]$Deploy
if ($ConfigureNginx) {
    $domainPattern = '^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$'
    if ([string]::IsNullOrWhiteSpace($Domain) -or $Domain -notmatch $domainPattern) {
        throw '-ConfigureNginx 需要合法的 FQDN：-Domain。'
    }
    $Domain = $Domain.ToLowerInvariant()
    $requiredPathParameters = if ($AllowInsecureHttp) {
        if ($TlsCertPath -or $TlsKeyPath) {
            throw '-AllowInsecureHttp 不能与 -TlsCertPath 或 -TlsKeyPath 一同使用。'
        }
        if ($BasicAuthFile) {
            throw '-AllowInsecureHttp 不使用 Nginx Basic Auth；请不要传入 -BasicAuthFile。'
        }
        @()
    }
    else {
        @(
            @{ Name = 'TlsCertPath'; Value = $TlsCertPath },
            @{ Name = 'TlsKeyPath'; Value = $TlsKeyPath },
            @{ Name = 'BasicAuthFile'; Value = $BasicAuthFile }
        )
    }
    foreach ($item in $requiredPathParameters) {
        if (-not (Test-SafeLinuxAbsolutePath $item.Value)) {
            throw "-ConfigureNginx 需要安全的 Linux 绝对路径：-$($item.Name)。"
        }
    }
    if (-not ($requestedDeploy -or $DryRun)) {
        throw '-ConfigureNginx 只能与 -Deploy 一同执行；可用 -DryRun 仅预览。'
    }
}
elseif ($AllowInsecureHttp -or $Domain -or $TlsCertPath -or $TlsKeyPath -or $BasicAuthFile) {
    throw '-AllowInsecureHttp、-Domain、-TlsCertPath、-TlsKeyPath 与 -BasicAuthFile 只能与 -ConfigureNginx 一同使用。'
}

if ($DryRun) {
    $Deploy = $false
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendDir = Join-Path $projectRoot 'frontend'
$distDir = Join-Path $frontendDir 'dist'
$sourceDb = Join-Path $projectRoot '.palace/qianlong.db'
$releaseName = 'release-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8)
$stagingRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("qianlong-palace-$releaseName")
$releaseDir = Join-Path $stagingRoot 'release'
$initialSnapshotDb = $null
$nginxConfig = $null

try {
    foreach ($relativePath in @('requirements.txt', 'src', 'deploy/Dockerfile', 'deploy/Dockerfile.dockerignore', 'deploy/docker-compose.yml', 'deploy/requirements-runtime.txt')) {
        if (-not (Test-Path -LiteralPath (Join-Path $projectRoot $relativePath))) {
            throw "缺少发布所需文件：$relativePath"
        }
    }
    if ($ConfigureNginx) {
        $nginxTemplateName = if ($AllowInsecureHttp) {
            'nginx-qianlong-palace-http.conf.template'
        }
        else {
            'nginx-qianlong-palace.conf.template'
        }
        $nginxTemplatePath = Join-Path $projectRoot "deploy/$nginxTemplateName"
        if (-not (Test-Path -LiteralPath $nginxTemplatePath)) {
            throw "缺少 Nginx 配置模板：$nginxTemplatePath"
        }
        $nginxConfig = (Get-Content -LiteralPath $nginxTemplatePath -Raw).Replace('__PALACE_DOMAIN__', $Domain)
        if (-not $AllowInsecureHttp) {
            $nginxConfig = $nginxConfig.
                Replace('__PALACE_TLS_CERT__', $TlsCertPath).
                Replace('__PALACE_TLS_KEY__', $TlsKeyPath).
                Replace('__PALACE_BASIC_AUTH_FILE__', $BasicAuthFile)
        }
        if ($nginxConfig -match '__PALACE_') {
            throw 'Nginx 配置模板仍含未替换占位符。'
        }
    }

    # 测试门禁排在前端构建之前：它更快，失败时不必白等一次 npm run build。
    if (-not $SkipTests) {
        $pythonExe = Join-Path $projectRoot '.venv/Scripts/python.exe'
        if (-not (Test-Path -LiteralPath $pythonExe)) {
            $fallbackPython = Get-Command python -ErrorAction SilentlyContinue
            if (-not $fallbackPython) {
                throw '未找到 Python 解释器，无法执行发布前测试。请先运行 setup.ps1，或显式使用 -SkipTests。'
            }
            $pythonExe = $fallbackPython.Source
        }
        Write-Host '发布前测试：pytest tests/'
        Push-Location $projectRoot
        try {
            Invoke-NativeCommand -FilePath $pythonExe -Arguments @('-m', 'pytest', 'tests/', '-q')
        }
        finally {
            Pop-Location
        }
    }
    else {
        Write-Warning '已跳过发布前测试（-SkipTests）。'
    }

    if (-not $SkipFrontendBuild) {
        if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
            throw '未找到 npm。请安装 Node.js，或在已构建前端后使用 -SkipFrontendBuild。'
        }
        Push-Location $frontendDir
        try {
            Invoke-NativeCommand -FilePath 'npm' -Arguments @('run', 'build')
        }
        finally {
            Pop-Location
        }
    }

    if (-not (Test-Path -LiteralPath (Join-Path $distDir 'index.html'))) {
        throw '未找到 frontend/dist/index.html。请先执行 npm run build，或不要使用 -SkipFrontendBuild。'
    }
    if ($InitializeData -and -not (Test-Path -LiteralPath $sourceDb)) {
        throw "-InitializeData 需要本地账本：$sourceDb"
    }

    New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $releaseDir 'frontend') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $releaseDir 'deploy') -Force | Out-Null

    # 白名单复制：发布包不包含 node_modules、.palace、.env、SSH 凭据或其他工作区文件。
    Copy-Item -LiteralPath (Join-Path $projectRoot 'requirements.txt') -Destination $releaseDir
    Copy-Item -LiteralPath (Join-Path $projectRoot 'src') -Destination (Join-Path $releaseDir 'src') -Recurse
    Copy-Item -LiteralPath $distDir -Destination (Join-Path $releaseDir 'frontend/dist') -Recurse
    foreach ($fileName in @('Dockerfile', 'Dockerfile.dockerignore', 'docker-compose.yml', 'requirements-runtime.txt')) {
        Copy-Item -LiteralPath (Join-Path $projectRoot "deploy/$fileName") -Destination (Join-Path $releaseDir "deploy/$fileName")
    }

    if ($InitializeData) {
        $pythonExe = Join-Path $projectRoot '.venv/Scripts/python.exe'
        if (-not (Test-Path -LiteralPath $pythonExe)) {
            $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
            if (-not $pythonCommand) {
                throw '首次账本迁移需要 Python（sqlite3.backup()）。未找到 .venv 或系统 python。'
            }
            $pythonExe = $pythonCommand.Source
        }
        $initialSnapshotDb = Join-Path $stagingRoot 'initial-qianlong.db'
        $backupProgram = @'
import sqlite3
import sys

source_path, snapshot_path = sys.argv[1:3]
source = sqlite3.connect(source_path)
snapshot = sqlite3.connect(snapshot_path)
try:
    source.backup(snapshot)
finally:
    snapshot.close()
    source.close()
'@
        Invoke-NativeCommand -FilePath $pythonExe -Arguments @('-c', $backupProgram, $sourceDb, $initialSnapshotDb)
        if (-not (Test-Path -LiteralPath $initialSnapshotDb)) {
            throw 'SQLite 一致性快照未生成。'
        }
    }
    Get-ChildItem -LiteralPath $releaseDir -Directory -Recurse -Force |
        Where-Object Name -eq '__pycache__' |
        Remove-Item -Recurse -Force

    $stagedFiles = Get-ChildItem -LiteralPath $releaseDir -File -Recurse -Force
    $stagedBytes = ($stagedFiles | Measure-Object -Property Length -Sum).Sum
    $stagedMegabytes = [Math]::Round(($stagedBytes / 1MB), 2)
    Write-Host "发布预览：$($stagedFiles.Count) 个文件，$stagedMegabytes MB"
    Write-Host "目标服务器：$Server；发布目录：$RemoteRoot/releases/$releaseName"
    Write-Host '数据边界：仅挂载服务器 /srv/qianlong-palace/data；发布包不含 SQLite 或密钥。'
    if ($InitializeData) {
        Write-Host "首次数据导入：已生成 sqlite3.backup() 一致性快照；仅当远端 $RemoteRoot/data/qianlong.db 不存在时导入。"
    }
    if ($ConfigureNginx) {
        $mappingMode = if ($AllowInsecureHttp) { 'HTTP（显式不安全模式；应用会话认证）' } else { 'TLS + Nginx Basic Auth' }
        Write-Host "Nginx 映射预览：$Domain -> 127.0.0.1:18787（$mappingMode）；目标 /home/software/nginx/conf/conf.d/qianlong-palace.conf"
    }

    if (-not $Deploy) {
        Write-Host '未设置 -Deploy，未连接服务器，也不会产生任何远端改动。'
        return
    }

    foreach ($commandName in @('ssh', 'scp')) {
        if (-not (Get-Command $commandName -ErrorAction SilentlyContinue)) {
            throw "未找到 $commandName。请安装并配置 OpenSSH 客户端。"
        }
    }

    $remoteStage = "$RemoteRoot/.staging/$releaseName"
    $remoteRelease = "$RemoteRoot/releases/$releaseName"
    $remoteStageCreated = $false
    try {
        Invoke-NativeCommand -FilePath 'ssh' -Arguments @($Server, "mkdir -p -- '$remoteStage'")
        $remoteStageCreated = $true
        Invoke-NativeCommand -FilePath 'scp' -Arguments @('-r', $releaseDir, "${Server}:${remoteStage}/")
        if ($InitializeData) {
            Invoke-NativeCommand -FilePath 'scp' -Arguments @($initialSnapshotDb, "${Server}:${remoteStage}/initial-qianlong.db")
        }
        if ($ConfigureNginx) {
            $renderedNginxConfig = Join-Path $stagingRoot 'nginx-qianlong-palace.conf'
            [System.IO.File]::WriteAllText($renderedNginxConfig, $nginxConfig, [System.Text.UTF8Encoding]::new($false))
            Invoke-NativeCommand -FilePath 'scp' -Arguments @($renderedNginxConfig, "${Server}:${remoteStage}/nginx-qianlong-palace.conf")
        }

        $initializeFlag = if ($InitializeData) { '1' } else { '0' }
        $configureNginxFlag = if ($ConfigureNginx) { '1' } else { '0' }
        $allowInsecureHttpFlag = if ($AllowInsecureHttp) { '1' } else { '0' }
        $remoteScript = @'
set -eu

root="$1"
stage="$2"
release="$3"
initialize_data="$4"
configure_nginx="$5"
domain="$6"
tls_cert_path="$7"
tls_key_path="$8"
basic_auth_file="$9"
allow_insecure_http="${10}"
env_file="$root/.env"
data_dir="$root/data"
release_dir="$root/releases/$release"
compose_file="$release_dir/deploy/docker-compose.yml"
previous_release="$(readlink -f "$root/current" 2>/dev/null || true)"

cleanup_stage() {
    rm -rf -- "$stage"
}
trap cleanup_stage EXIT

restore_previous() {
    if [ -n "$previous_release" ] && [ -f "$previous_release/deploy/docker-compose.yml" ]; then
        echo "尝试恢复旧版本容器：$previous_release" >&2
        docker compose --env-file "$env_file" -f "$previous_release/deploy/docker-compose.yml" up -d --build --remove-orphans || true
    else
        docker compose --env-file "$env_file" -f "$compose_file" stop || true
    fi
}

configure_nginx_mapping() {
    nginx_bin="/home/software/nginx/sbin/nginx"
    nginx_conf_dir="/home/software/nginx/conf/conf.d"
    nginx_target="$nginx_conf_dir/qianlong-palace.conf"
    nginx_config="$stage/nginx-qianlong-palace.conf"
    nginx_backup=""
    had_target="0"

    test -x "$nginx_bin" || { echo "未找到 Nginx：$nginx_bin" >&2; return 1; }
    case "$allow_insecure_http" in
        0)
            test -r "$tls_cert_path" || { echo "TLS 证书不可读：$tls_cert_path" >&2; return 1; }
            test -r "$tls_key_path" || { echo "TLS 私钥不可读：$tls_key_path" >&2; return 1; }
            test -r "$basic_auth_file" || { echo "Basic Auth 密码文件不可读：$basic_auth_file" >&2; return 1; }
            mapping_protocol="HTTPS"
            ;;
        1)
            if [ -n "$tls_cert_path" ] || [ -n "$tls_key_path" ] || [ -n "$basic_auth_file" ]; then
                echo "HTTP 模式不得传入 TLS 或 Nginx Basic Auth 配置。" >&2
                return 1
            fi
            mapping_protocol="HTTP（显式不安全模式）"
            ;;
        *)
            echo "无效的 HTTP 模式标识：$allow_insecure_http" >&2
            return 1
            ;;
    esac
    test -f "$nginx_config" || { echo "缺少渲染后的 Nginx 配置：$nginx_config" >&2; return 1; }

    nginx_dump="$($nginx_bin -T 2>&1)" || { echo "无法读取当前 Nginx 配置" >&2; return 1; }
    if ! printf '%s\n' "$nginx_dump" | grep -Eq '^[[:space:]]*include[[:space:]]+[^;]*conf\.d/\*\.conf;'; then
        echo "当前 nginx.conf 未包含 conf.d/*.conf，拒绝写入 $nginx_target" >&2
        return 1
    fi

    install -d -m 0755 "$nginx_conf_dir"
    if [ -e "$nginx_target" ]; then
        nginx_backup="$nginx_target.bak-$(date +%Y%m%d-%H%M%S)"
        cp -p -- "$nginx_target" "$nginx_backup"
        had_target="1"
    fi

    restore_nginx_config() {
        if [ "$had_target" = "1" ]; then
            cp -p -- "$nginx_backup" "$nginx_target"
        else
            rm -f -- "$nginx_target"
        fi
        if "$nginx_bin" -t; then
            "$nginx_bin" -s reload || true
        fi
    }

    if ! install -m 0644 "$nginx_config" "$nginx_target"; then
        echo "写入 Nginx server 配置失败" >&2
        return 1
    fi
    if ! "$nginx_bin" -t; then
        echo "Nginx 配置校验失败，正在恢复备份。" >&2
        restore_nginx_config
        return 1
    fi
    if ! "$nginx_bin" -s reload; then
        echo "Nginx reload 失败，正在恢复备份。" >&2
        restore_nginx_config
        return 1
    fi
    echo "Nginx 映射已加载：$domain -> 127.0.0.1:18787（$mapping_protocol）"
}

test -f "$env_file" || { echo "缺少服务器环境文件：$env_file" >&2; exit 1; }
for key in PALACE_ALLOWED_HOSTS PALACE_WRITE_TOKEN PALACE_AUTH_USERNAME PALACE_AUTH_PASSWORD PALACE_SESSION_SECRET; do
    grep -Eq "^${key}=.+" "$env_file" || { echo "环境文件缺少非空 $key" >&2; exit 1; }
done
if [ "$configure_nginx" = "1" ]; then
    configured_domain="$(sed -n 's/^PALACE_ALLOWED_HOSTS=//p' "$env_file" | tail -n 1 | cut -d, -f1 | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')"
    [ "$configured_domain" = "$domain" ] || {
        echo "PALACE_ALLOWED_HOSTS 首个域名（$configured_domain）必须与 -Domain（$domain）一致。" >&2
        exit 1
    }
    # 会话 Cookie 的 Secure 标记必须与 Nginx 的协议模式一致，否则登录会静默失效：
    # HTTP 模式下带 Secure 的 Cookie 浏览器根本不会回传，表现为"登录成功但立刻又被踢回登录页"。
    configured_insecure="$(sed -n 's/^PALACE_INSECURE_HTTP=//p' "$env_file" | tail -n 1 | tr -d '[:space:]')"
    if [ "$allow_insecure_http" = "1" ]; then
        case "$configured_insecure" in
            1|true|TRUE|yes|YES|on|ON) : ;;
            *)
                echo "HTTP 模式需要在 $env_file 设置 PALACE_INSECURE_HTTP=1，否则登录会话无法保持。" >&2
                exit 1
                ;;
        esac
    else
        case "$configured_insecure" in
            ''|0|false|FALSE|no|NO|off|OFF) : ;;
            *)
                echo "HTTPS 模式下 $env_file 不能保留 PALACE_INSECURE_HTTP=$configured_insecure；请删除该行或置 0。" >&2
                exit 1
                ;;
        esac
    fi
fi
test -d "$stage/release" || { echo "上传的发布包不完整：$stage/release" >&2; exit 1; }
test ! -e "$release_dir" || { echo "发布目录已存在：$release_dir" >&2; exit 1; }

# 先校验 Compose 配置，再移动发布目录；失败不会影响 current 所指向的旧版本。
docker compose --env-file "$env_file" -f "$stage/release/deploy/docker-compose.yml" config -q
install -d -m 0750 "$root/releases"
install -d -o 10001 -g 10001 -m 0750 "$data_dir"

if [ "$initialize_data" = "1" ]; then
    if [ ! -e "$data_dir/qianlong.db" ]; then
        test -f "$stage/initial-qianlong.db" || { echo "缺少待导入账本" >&2; exit 1; }
        install -o 10001 -g 10001 -m 0600 "$stage/initial-qianlong.db" "$data_dir/qianlong.db"
        echo "已导入首次 SQLite 账本。"
    else
        echo "远端账本已存在，跳过首次导入。"
    fi
fi

mv "$stage/release" "$release_dir"
if ! docker compose --env-file "$env_file" -f "$compose_file" up -d --build --remove-orphans; then
    echo "新版本启动失败；current 未切换。" >&2
    restore_previous
    exit 1
fi

container_id="$(docker compose --env-file "$env_file" -f "$compose_file" ps -q palace)"
if [ -z "$container_id" ]; then
    echo "未找到 palace 容器；current 未切换。" >&2
    restore_previous
    exit 1
fi
health=""
for attempt in $(seq 1 20); do
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")"
    [ "$health" = "healthy" ] && break
    [ "$health" = "unhealthy" ] && break
    sleep 2
done

if [ "$health" != "healthy" ]; then
    echo "新版本健康检查失败（$health）；current 未切换。" >&2
    restore_previous
    exit 1
fi

if [ "$configure_nginx" = "1" ]; then
    if ! configure_nginx_mapping; then
        echo "Nginx 自动配置失败；current 未切换。" >&2
        restore_previous
        exit 1
    fi
fi

ln -sfn "$release_dir" "$root/current"
echo "部署完成：$release_dir"
'@
        $remoteScript | & ssh $Server "sh -s -- '$RemoteRoot' '$remoteStage' '$releaseName' '$initializeFlag' '$configureNginxFlag' '$Domain' '$TlsCertPath' '$TlsKeyPath' '$BasicAuthFile' '$allowInsecureHttpFlag'"
        if ($LASTEXITCODE -ne 0) {
            throw "服务器部署失败（exit=$LASTEXITCODE）。current 未在健康检查通过前切换。"
        }
        $remoteStageCreated = $false
    }
    catch {
        if ($remoteStageCreated) {
            Write-Warning "远端发布未完成，清理 staging：$remoteStage"
            & ssh $Server "rm -rf -- '$remoteStage'"
            if ($LASTEXITCODE -ne 0) {
                Write-Warning "无法自动清理远端 staging：$remoteStage"
            }
        }
        throw
    }
}
finally {
    if (Test-Path -LiteralPath $stagingRoot) {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force
    }
}
