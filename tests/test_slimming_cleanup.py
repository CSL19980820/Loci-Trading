"""Exercise the actual offline cleanup CLI on disposable legacy data."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT/'deploy/server/retire_slim_state.py'


def seed(root):
    root.mkdir()
    for folder in (root, root/'tenants'/'fixture'):
        folder.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(folder/'ops.db')) as conn, conn:
            conn.executescript('''
                CREATE TABLE jobs(id TEXT PRIMARY KEY, kind TEXT, config_json TEXT);
                CREATE TABLE job_runs(id TEXT PRIMARY KEY,job_id TEXT,kind TEXT);
                CREATE TABLE paper_cabins(id TEXT PRIMARY KEY);
                CREATE TABLE paper_positions(id TEXT PRIMARY KEY,cabin_id TEXT REFERENCES paper_cabins(id));
                CREATE TABLE alert_rules(id TEXT PRIMARY KEY,payload TEXT);
                INSERT INTO paper_cabins VALUES('old');
                INSERT INTO paper_positions VALUES('position','old');
                INSERT INTO jobs VALUES('old','paper_eod','{}');
                INSERT INTO jobs VALUES('brief','intel_brief','{}');
                INSERT INTO jobs VALUES('screen','screen','{"strategy":"keep"}');
                INSERT INTO job_runs VALUES('retired','old','paper_eod');
                INSERT INTO job_runs VALUES('retained','screen','screen');
                INSERT INTO alert_rules VALUES('keep','original');
            ''')
        (folder/'mcp.json').write_text(json.dumps({'mcpServers': {
            'wudao': {'url':'https://example.invalid/wudao','token':'fixture-only'},
            'hithink-finance-a-share': {'url':'https://fuyao.aicubes.cn/mcp/a-share','token':'remove'},
        }}), encoding='utf-8')
    with closing(sqlite3.connect(root/'community.db')) as conn, conn:
        conn.execute('CREATE TABLE comments(id TEXT)')
    (root/'palace.db').write_bytes(b'untouched ledger sentinel')
    (root/'market.db').write_bytes(b'untouched market sentinel')
    (root/'loci.config.json').write_text(json.dumps({
        'session_secret':'fixture-kept', 'lane_providers':{'tdx':{'enabled':True},'eastmoney':{'enabled':True}},
        'lane_routes':{'hist_daily':{'mode':'manual','provider_id':'eastmoney'}},
        'wudao_mcp':{'hist_daily_primary':True,'quota':{'daily_total':3000}},
    }),encoding='utf-8')


def invoke(root, *args):
    return subprocess.run([sys.executable, str(SCRIPT), '--data-root', str(root), *map(str,args)],
                          capture_output=True, text=True, encoding='utf-8', check=False)


def test_preview_apply_preserves_core_and_backups_legacy(tmp_path):
    root=tmp_path/'data'; seed(root)
    preview=invoke(root)
    assert preview.returncode == 0, preview.stderr
    plan=json.loads(preview.stdout)
    assert len(plan['databases']) == 2 and plan['files'] == ['community.db']
    assert not plan['applied'] and (root/'community.db').exists()
    backup=tmp_path/'backup'
    result=invoke(root, '--apply', '--application-stopped', '--backup-dir',backup)
    assert result.returncode == 0, result.stderr
    assert 'fixture-only' not in result.stdout and 'session_secret' not in result.stdout
    assert not (root/'community.db').exists() and (backup/'community.db').exists()
    for folder in (root,root/'tenants'/'fixture'):
        with closing(sqlite3.connect(folder/'ops.db')) as conn:
            assert not conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'paper_%'").fetchall()
            assert conn.execute('SELECT id FROM jobs').fetchall() == [('screen',)]
            assert conn.execute('SELECT id FROM job_runs').fetchall() == [('retained',)]
            assert conn.execute('SELECT * FROM alert_rules').fetchall() == [('keep','original')]
        with closing(sqlite3.connect(backup/folder.relative_to(root)/'ops.db')) as conn:
            assert conn.execute('SELECT COUNT(*) FROM paper_positions').fetchone()[0] == 1
        assert set(json.loads((folder/'mcp.json').read_text())['mcpServers']) == {'wudao'}
    assert (root/'palace.db').read_bytes() == b'untouched ledger sentinel'
    assert (root/'market.db').read_bytes() == b'untouched market sentinel'
    config=json.loads((root/'loci.config.json').read_text())
    assert config['session_secret'] == 'fixture-kept'
    assert set(config['lane_providers']) == {'tdx'} and config['lane_routes'] == {}
    assert config['wudao_mcp'] == {'quota':{'daily_total':3000}}
    again=json.loads(invoke(root).stdout)
    assert all(not row['drop_tables'] and row['retired_jobs']==0 for row in again['databases'])
    assert again['files']==again['configs']==[]
    restore_script = ROOT/'deploy/server/restore_slim_state.py'
    restored = subprocess.run([sys.executable, str(restore_script), '--data-root', str(root),
                               '--backup-dir', str(backup), '--application-stopped'],
                              capture_output=True, text=True, encoding='utf-8')
    assert restored.returncode == 0, restored.stderr
    assert (root/'community.db').exists()
    for folder in (root, root/'tenants'/'fixture'):
        with closing(sqlite3.connect(folder/'ops.db')) as conn:
            assert conn.execute('SELECT COUNT(*) FROM paper_positions').fetchone()[0] == 1
            assert conn.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] == 3
    assert (root/'palace.db').read_bytes() == b'untouched ledger sentinel'


@pytest.mark.parametrize('args',[('--apply',),('--apply','--application-stopped')])
def test_apply_refuses_without_required_safety_parameters(tmp_path,args):
    root=tmp_path/'data'; seed(root)
    result=invoke(root,*args)
    assert result.returncode != 0
    assert (root/'community.db').exists()
