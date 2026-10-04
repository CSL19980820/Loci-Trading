"""Public lifespan delegation and application-only deployment stay narrowly scoped."""
import asyncio
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_optional_gateway_public_entry_delegates_only_when_called(monkeypatch):
    import src.ai as api
    from src.ai.infrastructure import grpc_gateway
    calls=[]
    sentinel=object()
    async def start():
        calls.append('start')
        return sentinel
    monkeypatch.setattr(grpc_gateway,'start_from_env',start)
    assert calls == []
    assert asyncio.run(api.start_grpc_from_env()) is sentinel
    assert calls == ['start']


def test_research_recovery_public_entry_preserves_return_value(monkeypatch):
    import src.research as api
    from src.research.infrastructure import backtest_jobs
    calls=[]
    def recover():
        calls.append('recover')
        return 7
    monkeypatch.setattr(backtest_jobs,'recover_research_jobs',recover)
    assert calls == []
    assert api.recover_research_jobs() == 7
    assert calls == ['recover']


def test_linux_deployment_script_uses_lf():
    assert bytes([13]) not in (ROOT/'deploy/server/server-deploy.sh').read_bytes()


def _bash():
    git=shutil.which('git')
    choices=([str(Path(git).parent.parent/'bin/bash.exe')] if git and os.name=='nt' else [])
    choices += [shutil.which('bash') or '']
    for name in choices:
        if name and Path(name).is_file():
            return name
    pytest.skip('Bash is unavailable on this test host')


@pytest.mark.parametrize('http_status,exit_code',[('200',0),('503',1)])
def test_app_only_deployment_checks_existing_proxy_without_reloading(http_status,exit_code):
    text=(ROOT/'deploy/server/server-deploy.sh').read_text(encoding='utf-8')
    begin=text.index('step "接管 ')
    end=text.index('step "安装存储治理定时任务"',begin)
    fragment=text[begin:end]
    harness='''set -euo pipefail
MANAGE_NGINX=0
SITE_DOMAIN=fixture.invalid
step() { :; }
note() { :; }
die() { echo "$*" >&2; exit 1; }
curl() { printf '%s' "$FIXTURE_STATUS"; }
'''+fragment
    result=subprocess.run([_bash(),'-c',harness],env={**os.environ,'FIXTURE_STATUS':http_status},
                          text=True,encoding='utf-8',capture_output=True,timeout=10)
    assert result.returncode==exit_code,result.stderr
    if exit_code:
        assert '503' in result.stderr
