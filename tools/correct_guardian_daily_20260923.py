"""Prepare evidence-checked corrections of the 2026-09-21 and 09-23 reviews.

Dry-run is read-only. Apply requires an explicit SQLite backup and commits both
new report revisions and experience revision 8 in one SQLite transaction. It
never replays watchlist updates or sends a notification.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
import time
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ledger import GuardianStore
from src.ledger.domain.guardian_experience import (
    MAX_EXPERIENCES, MAX_EXPERIENCE_CHARACTERS, experience_text, validate_experience,
)
from src.ops.application.guardian_review_digest import notification_digest
from src.ops.application.guardian_review_format import report_body


DAY = '2026-09-23'
KEY = f'daily:{DAY}'
EXPECTED_REPORT_SHA256 = '5b6498ea72a88f92cba9816d5b39bcca0803be8d4982f54a412b2d3671cd736c'
OLD_DAY = '2026-09-21'
OLD_KEY = f'daily:{OLD_DAY}'
EXPECTED_OLD_SHA256 = '98f675b0144c819449e8ec1bbf1e441b177e5b7a0d042a91f2078673f7bdf8ac'
RELEASE_IMAGE = 'loci-qianlong:guardian-deadline-20260923'
RELEASE_AT = '2026-09-23T02:00:18.260105+00:00'
REASON = ('纠正历史规则生效时间与盘前计划执行归因：688825两笔成交早于科创板禁买规则上线；'
          '区分原合同执行和盘中修订，账务、成交及观察决定保持原样。')
OLD_REASON = ('纠正09:25待复核意图的因果归因：五笔意图均设09:30失效，'
              '未有逐笔接续回执；不能证明09:30轮次失败直接导致其作废。'
              '旧经验已由后续复盘承接，本次历史更正不回写当前经验库。')


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def replace_once(value: str, old: str, new: str, label: str) -> str:
    require(value.count(old) == 1, f'{label} 与预期原文不一致，拒绝更正')
    return value.replace(old, new)


def table_digest(conn: sqlite3.Connection, table: str, columns: str) -> str:
    """Stable audit digest over complete rows; table/column names are fixed here."""
    digest = sha256()
    for row in conn.execute(f'SELECT {columns} FROM {table} ORDER BY rowid'):
        value = json.dumps(tuple(row), ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        digest.update(len(value).to_bytes(8, 'big'))
        digest.update(value)
    return digest.hexdigest()


def revise_analysis(source: dict) -> tuple[dict, list[str]]:
    """Revise only claims disproved by the original cycles and release receipt."""
    a = deepcopy(source)
    edits: list[str] = []

    def edit(path: tuple[str | int, ...], old: str, new: str) -> None:
        owner = a
        for part in path[:-1]:
            owner = owner[part]
        key = path[-1]
        label = '.'.join(map(str, path))
        owner[key] = replace_once(owner[key], old, new, label)
        edits.append(label)

    edit(('summary',),
         '盘前三类计划落地：京东方减4000@6.14（收6.02）、新易盛按跌破452减100@450.70（收451.20）、中天200股由36.60风险合同在09:30开盘成交（收35.78，-2.98%）；',
         '中天200股由既有36.60止损合同在09:30成交（收35.78，-2.98%）；京东方按盘中修订依据减4000@6.14（收6.02），新易盛按盘中新提出的跌破452判断减100@450.70（收451.20）；')
    edit(('summary',),
         '主要问题两项：长鑫科技为688科创板，本账户不可买入却成交400股，持仓按账本保留、不得再加、需核查拦截环节；长鑫两笔买价',
         '规则时序纠正：长鑫科技两笔买入早于10:00:18上线的科创板禁买规则，不构成当时的漏拦截；400股保留，现行规则禁止再加仓。买点问题：长鑫两笔买价')
    edit(('notification_summary',),
         '需处理：长鑫科技属科创板，本账户不可买入却成交400股，持仓保留、不得再加，并核查拦截环节。',
         '规则时序更正：长鑫两笔买入早于10:00:18禁买规则上线；400股保留，现行规则禁止再加仓。')
    edit(('assessments', 0), '计划执行基本落地且无程序拒单：', '既有合同执行与盘中修订，全天无程序拒单：')
    edit(('assessments', 0), '新易盛09:57按跌破452条件减100', '新易盛09:57按盘中新提出的跌破452判断减100')
    edit(('assessments', 0), '三条按计划执行，结果方向一致。',
         '中天按既有合同执行，京东方改变原触发依据，新易盛属于盘中新判断；三笔结果与收盘价的比较如上。')
    edit(('assessments', 2),
         '科创板执行冲突：688825长鑫科技属688科创板，本账户可买板块仅沪深主板与创业板，但09:42买200股、09:57加200股共400股成交（约23,632元）。账本按已成交保留、9/24起可卖，后续不得再加仓；需核验买入前置校验为何未按板块拦截。这是当日最重要的流程问题，与价格判断对错无关。',
         '规则生效时间核对：688825长鑫科技于09:42买200股、09:57加200股，两笔均早于科创板禁买规则10:00:18上线；原始轮次权限快照也未列可买板块限制。因此不能把历史成交判为当时的拦截失效。约23,632元持仓按账本保留，9/24起可卖；现行规则禁止再买入或加仓。买点判断另行评价。')
    edit(('assessments', 7), '当日盘前计划仍由09:30后轮次与既有风险合同执行',
         '盘前条件由09:30后轮次重新核验，中天既有风险合同执行')
    edit(('assessments', 7), '09:25竞价轮次连续第三日异常：', '09:25竞价轮次研究超时：')
    edit(('assessments', 7),
         '与9/21（有意图但09:30失败作废）、9/22（deferred被09:30复核）形态不同。',
         '9/21旧流程五笔deferred有效期09:30、opening_plans=0且缺少逐笔接续，不能归因于09:30失败；9/22新版预案600487于09:30执行300股、600522同轮放弃。')
    reviews = {item['code']: item for item in a['stock_reviews']}
    require(len(reviews) == len(a['stock_reviews']), '逐股复盘代码重复')
    reviews['688825']['assessment'] = replace_once(
        reviews['688825']['assessment'],
        '两个问题：一是688科创板不属本账户可买板块，两笔成交与限制冲突，持仓保留、9/24可卖、不得再加；二是加仓时价贴日高，收盘低于加仓价1.01%。',
        '规则与买点分开看：科创板禁买规则在10:00:18才上线，两笔成交不构成当时的拦截失效；400股保留、9/24可卖，现行规则禁止再加。加仓时价贴日高，收盘低于加仓价1.01%。',
        'stock_reviews.688825.assessment')
    edits.append('stock_reviews.688825.assessment')
    reviews['300502']['assessment'] = replace_once(
        reviews['300502']['assessment'], '09:57按计划跌破452减100股',
        '09:57按盘中新判断跌破452减100股', 'stock_reviews.300502.assessment')
    edits.append('stock_reviews.300502.assessment')
    edit(('operational_notes', 0),
         '（9/21 deferred后09:30失败作废、9/22 deferred被09:30复核、9/23研究超时未产生意图）',
         '（9/21旧流程五笔deferred、opening_plans=0且缺逐笔接续，不能归因于09:30失败；9/22新版预案600487在09:30执行300股、600522同轮放弃；9/23研究超时未产生意图）')
    edit(('operational_notes', 0), '竞价轮次已连续三日形态异常', '竞价流程的缺口分日有别')
    edit(('operational_notes', 1),
         '688825两笔买入未被板块校验拦截：账户可买板块为沪深主板与创业板，688前缀不在其中，但09:42与09:57两笔成交。需核验执行前置校验(board eligibility)为何未生效；此为工程问题，不改写已成交账务，也不据历史成交推断权限已放开。',
         '688825两笔买入发生在09:42与09:57，均早于10:00:18上线的科创板禁买规则；当时轮次的权限快照没有可买板块限制。不能倒用新规则判定历史执行器漏拦截。账务不改写；现行规则禁止再买入或加仓，历史持仓可减仓退出。部署时间由生产部署回执核对。')
    edit(('lessons', 0, 'hypothesis'), '当日盘前计划仍由09:30后轮次与既有风险合同执行',
         '盘前条件由09:30后轮次重新核验，中天既有风险合同执行')
    edit(('lessons', 0, 'hypothesis'),
         '与9/21（有意图但09:30失败作废）、9/22（deferred被09:30复核）不同。',
         '与9/21旧流程五笔deferred有效期09:30、opening_plans=0且无逐笔接续不同；9/22新版预案600487于09:30执行300股、600522同轮放弃，不证明旧deferred自动续传。')
    edit(('lessons', 0, 'hypothesis'), '09:25竞价轮次出现第三种失效形态：',
         '09:25竞价轮次出现研究超时：')
    edit(('lessons', 0, 'validation_plan'), '区分有意图但作废与未产生意图',
         '区分意图到期且缺少接续与未产生意图')
    a['lessons'][1]['hypothesis'] = (
        '历史规则生效时间纠正：688825于9/23 09:42及09:57买入400股；科创板禁买规则于10:00:18才部署，'
        '当轮权限快照未含该限制，不能判作当时执行器漏拦截。现行规则禁止再买入或加仓，历史持仓可减仓退出。')
    a['lessons'][1]['validation_plan'] = (
        '复盘逐笔核对成交时间、当轮规则快照和部署回执；新规则生效后的688/689买单再核验模型及记账双重拦截。')
    edits.append('lessons.1')
    experiences = {item['id']: item for item in a['experience']}
    require(len(experiences) == len(a['experience']), '经验编号重复')
    experiences['deferred_intent']['hypothesis'] = (
        '9/21旧流程五笔deferred有效期09:30、opening_plans=0，无逐笔接续；09:30失败不能据此定为致因。'
        '9/22新版预案逐笔：600487于09:30执行300股、600522同轮放弃；不能推论旧deferred自动续传。')
    experiences['deferred_intent']['validation_plan'] = (
        '逐日核对09:25意图有效期、开盘复核/成交/拒绝/到期回执和轮次状态；不从未成交反推续传机制。')
    edits.append('experience.deferred_intent')
    experiences['board_eligibility']['hypothesis'] = (
        '9/23 09:42与09:57两笔688825成交早于科创板禁买规则10:00:18上线；当轮权限快照未含板块限制，'
        '不能判为漏拦截。400股保留；现行规则禁止再买入或加仓，可减仓退出。')
    experiences['board_eligibility']['validation_plan'] = (
        '按成交时间、当轮权限快照和部署回执归因；新规则生效后的688/689买单核验模型及记账前置拦截。')
    edits.append('experience.board_eligibility')
    plans = {item['code']: item for item in a['plans']}
    require(len(plans) == len(a['plans']), '计划股票代码重复')
    plans['601208']['trigger'] = replace_once(
        plans['601208']['trigger'], '若冲至58-59滞涨则按合同了结。',
        '若冲至58-59滞涨，届时重新研判是否主动卖出；现有止盈合同触发价仍为59.5。',
        'plans.601208.trigger')
    edits.append('plans.601208.trigger')
    edit(('next_steps', 4), '为连续第三日形态异常', '是需要单独排查的研究超时')
    a['experience'] = validate_experience(a['experience'])
    return a, list(dict.fromkeys(edits))


def revise_old_analysis(source: dict) -> tuple[dict, list[str]]:
    a = deepcopy(source)
    changes = []
    edits = (
        ('summary', None,
         '盘前5笔策略买入09:25全部deferred、09:30轮次failed后作废',
         '盘前5笔买入意图09:25仅记录为deferred、均设09:30失效；09:30轮次failed但未给出五笔逐笔接续回执，不能证明失败直接导致作废'),
        ('notification_summary', None,
         '盘前5笔策略买入09:25全部deferred、09:30轮次failed后作废',
         '盘前5笔意图09:25仅deferred且09:30失效；09:30轮次failed，未有逐笔接续回执，不能归因其直接作废'),
        ('assessments', 0,
         '09:25以deferred挂起、valid_until=09:30，09:30轮次failed后未再出现，全天零拒单、零成交——这是执行/流程事实，不是主动放弃。',
         '09:25仅记录deferred（不是挂单），valid_until=09:30；09:30轮次failed但未给五笔买单逐笔执行、拒绝或放弃回执，五笔全天均未成交。期限到点与缺少接续是事实，不能证明失败直接导致作废，也不能称模型主动放弃。'),
        ('operational_notes', 1,
         '09:25轮次按流程不成交、意图valid_until=09:30，而09:30轮次failed，导致5笔开盘建仓意图全部失效；若要使其可执行，需要把valid_until设到09:35之后或让deferred意图在下一个成功轮次续传——这是流程缺口，不是交易结论。',
         '09:25轮次按流程不成交，五笔仅deferred且valid_until=09:30；09:30轮次failed的拒单只涉及亨通止盈，未对五笔买入给出逐笔复核。五笔未成交且未见接续，不能把未成交归因于该失败轮次。应核验有效期是否覆盖开盘复核，并逐笔记录等待、执行、放弃或到期。'),
    )
    for field, index, old, new in edits:
        label = f'{field}.{index}' if index is not None else field
        if index is None:
            a[field] = replace_once(a[field], old, new, label)
        else:
            a[field][index] = replace_once(a[field][index], old, new, label)
        changes.append(label)
    # Historical revision 4 must not replace experience revision 8. Revision 3
    # remains archived with the original experience text.
    require(isinstance(a.get('experience'), list), '历史报告经验原文缺失')
    a['experience'] = None
    changes.append('experience')
    return a, changes


def read_snapshot(db: Path, receipt_path: Path, *, expected_sha256: str = EXPECTED_REPORT_SHA256,
                  expected_old_sha256: str = EXPECTED_OLD_SHA256) -> dict:
    require(db.is_file(), '账本文件不存在')
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    require(receipt.get('image') == RELEASE_IMAGE and receipt.get('deployed_at') == RELEASE_AT,
            '部署回执镜像或生效时间不符')
    require({'src/ledger/domain/guardian_account.py', 'src/ops/application/guardian_decision.py'}
            <= set(receipt.get('changed_files') or []), '部署回执未包含买入规则与执行校验文件')
    conn = sqlite3.connect(f'file:{db.as_posix()}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    try:
        require(conn.execute('PRAGMA quick_check').fetchone()[0] == 'ok', '账本 quick_check 失败')
        row = conn.execute('SELECT status,result_json FROM guardian_reports WHERE report_key=?', (KEY,)).fetchone()
        require(row is not None and row['status'] == 'success', '日报不是已完成状态')
        original_hash = sha256(row['result_json'].encode('utf-8')).hexdigest()
        require(original_hash == expected_sha256, '日报原文哈希变化，拒绝覆盖')
        report = json.loads(row['result_json'])
        require(report.get('revision') == 1 and report.get('facts', {}).get('trade_date') == DAY,
                '目标不是 9/23 日报原始版本')
        require(report['facts']['experience']['revision'] == 6, '原报告经验基线不是 rev6')
        require(report['facts']['account']['equity_cents'] == 20_596_387
                and report['facts']['period_pnl_cents'] == -648, '账务基线变化')
        fills = (
            ('2026-09-23T09:40:00+08:00:0000', 'buy', 5891, '2026-09-23T09:40:00+08:00'),
            ('2026-09-23T09:55:00+08:00:0001', 'add', 5922, '2026-09-23T09:55:00+08:00'),
        )
        release_at = datetime.fromisoformat(RELEASE_AT)
        for trade_id, action, price, slot in fills:
            trade = conn.execute('SELECT code,occurred_at,detail_json FROM guardian_trades WHERE id=?',
                                 (trade_id,)).fetchone()
            require(trade is not None and trade['code'] == '688825', f'{trade_id} 成交流水缺失')
            detail = json.loads(trade['detail_json'])
            require(detail['action'] == action and detail['quantity'] == 200
                    and detail['price_cents'] == price and detail['quote_source'] == 'wudao',
                    f'{trade_id} 成交与预期不符')
            require(datetime.fromisoformat(trade['occurred_at']) < release_at,
                    f'{trade_id} 不早于规则上线')
            cycle = conn.execute('SELECT status,result_json FROM guardian_cycles WHERE slot=?', (slot,)).fetchone()
            require(cycle is not None and cycle['status'] == 'success', f'{slot} 轮次缺失')
            policy = json.loads(cycle['result_json'])['decision_context']['position_policy']
            require('buyable_boards' not in policy and 'buyable_code_prefixes' not in policy,
                    f'{slot} 当轮权限快照已含禁买限制')
        old_trade = conn.execute("SELECT detail_json FROM guardian_trades WHERE code='300502' AND slot='2026-09-21T10:00:00+08:00'").fetchone()
        require(old_trade is not None and json.loads(old_trade[0])['price_cents'] == 45912,
                '9/21 新易盛原始成交不符')
        exp_row = conn.execute('SELECT * FROM guardian_experience_versions ORDER BY revision DESC LIMIT 1').fetchone()
        require(exp_row is not None and exp_row['revision'] == 7
                and exp_row['source_report'] == KEY and exp_row['source_revision'] == 1,
                '当前经验不是目标日报产生的 rev7')
        current_experience = json.loads(exp_row['items_json'])
        current_text = experience_text(current_experience)
        experience_snapshot = {key: exp_row[key] for key in ('revision', 'source_report', 'source_revision',
                                                             'trade_date', 'created_at')}
        experience_snapshot.update(items=current_experience, origins=json.loads(exp_row['origins_json']),
                                   text=current_text, characters=len(current_text),
                                   max_characters=MAX_EXPERIENCE_CHARACTERS, max_items=MAX_EXPERIENCES)
        require(current_experience == report['analysis']['experience'], '当前经验已偏离原日报，拒绝全量替换')
        old_row = conn.execute('SELECT status,result_json FROM guardian_reports WHERE report_key=?', (OLD_KEY,)).fetchone()
        require(old_row is not None and old_row['status'] == 'success', '9/21 历史日报不是完成状态')
        old_hash = sha256(old_row['result_json'].encode('utf-8')).hexdigest()
        require(old_hash == expected_old_sha256, '9/21 历史日报原文哈希变化')
        old_report = json.loads(old_row['result_json'])
        require(old_report.get('revision') == 3 and old_report['facts']['trade_date'] == OLD_DAY,
                '9/21 目标不是历史 rev3')
        require(old_report['facts']['period_pnl_cents'] == 77023
                and old_report['facts']['account']['equity_cents'] == 20_621_373,
                '9/21 账务基线变化')
        opening = conn.execute("SELECT status,result_json FROM guardian_cycles WHERE slot='2026-09-21T09:25:00+08:00'").fetchone()
        failed = conn.execute("SELECT status,result_json FROM guardian_cycles WHERE slot='2026-09-21T09:30:00+08:00'").fetchone()
        require(opening is not None and opening['status'] == 'success'
                and failed is not None and failed['status'] == 'failed', '9/21 关键轮次状态变化')
        opening_result, failed_result = json.loads(opening['result_json']), json.loads(failed['result_json'])
        deferred = opening_result.get('deferred', [])
        require(len(deferred) == 5 and all(x['execution']['valid_until'] == '2026-09-21T09:30:00+08:00'
                                           for x in deferred), '9/21 五笔意图及有效期变化')
        deferred_codes = {x['code'] for x in deferred}
        require(not deferred_codes.intersection(x['code'] for field in ('fills', 'rejects', 'decisions')
                                                for x in failed_result.get(field, [])),
                '9/21 09:30 已给出五笔意图的逐笔回执')
        require(len(failed_result.get('rejects', [])) == 1
                and failed_result['rejects'][0]['code'] == '600487', '9/21 09:30 拒单性质变化')
        middle_row = conn.execute("SELECT status,result_json FROM guardian_reports WHERE report_key='daily:2026-09-22'").fetchone()
        require(middle_row is not None and middle_row['status'] == 'success', '9/22 日报缺失')
        middle = json.loads(middle_row['result_json'])
        require(middle.get('revision') == 2, '9/22 日报版本变化')
        plans = middle['facts']['opening_plan_reconciliation']
        require(len(plans) == 2, '9/22 竞价预案数量变化')
        actual = {p['order']['code']: (p['status'], p['filled_quantity'], p['source_slot'],
                                      p.get('last_review_slot')) for p in plans}
        require(actual == {
            '600487': ('executed', 300, '2026-09-22T09:25:00+08:00', '2026-09-22T09:30:00+08:00'),
            '600522': ('abandoned', 0, '2026-09-22T09:25:00+08:00', '2026-09-22T09:30:00+08:00'),
        }, '9/22 两笔竞价预案的逐笔结论变化')
        return {'report': report, 'original_sha256': original_hash,
                'experience_snapshot': experience_snapshot,
                'old_report': old_report, 'old_sha256': old_hash,
                'middle_sha256': sha256(middle_row['result_json'].encode('utf-8')).hexdigest(),
                'receipt_sha256': sha256(receipt_path.read_bytes()).hexdigest(),
                'portfolio_before': conn.execute('SELECT state_json FROM guardian_portfolio WHERE id=1').fetchone()[0],
                'trade_digest': table_digest(conn, 'guardian_trades', 'id,slot,code,occurred_at,detail_json'),
                'cycle_digest': table_digest(conn, 'guardian_cycles', 'slot,started,status,result_json')}
    finally:
        conn.close()


def make_candidate(snapshot: dict, *, at: str) -> tuple[dict, list[str]]:
    result = deepcopy(snapshot['report'])
    analysis, edits = revise_analysis(result['analysis'])
    result['analysis'] = analysis
    release_ref = 'release:guardian-deadline-20260923'
    cycle_refs = ['cycle:2026-09-23T09:40:00+08:00', 'cycle:2026-09-23T09:55:00+08:00']
    result['facts']['evidence_ids'] = list(dict.fromkeys([
        *result['facts']['evidence_ids'], *cycle_refs, release_ref,
    ]))
    result['facts']['correction_evidence'] = {
        release_ref: {'kind': 'production_deployment_receipt', 'sha256': snapshot['receipt_sha256'],
                      'image': RELEASE_IMAGE, 'deployed_at': RELEASE_AT},
    }
    analysis['lessons'][1]['evidence_ids'] = list(dict.fromkeys([
        *analysis['lessons'][1]['evidence_ids'], *cycle_refs, release_ref,
    ]))
    board = next(item for item in analysis['experience'] if item['id'] == 'board_eligibility')
    board['evidence_ids'] = [*cycle_refs, release_ref]
    analysis['experience'] = validate_experience(analysis['experience'])
    result['facts']['experience'] = deepcopy(snapshot['experience_snapshot'])
    result['facts']['correction_reason'] = REASON
    result['revision'] = 2
    result['created_at'] = at
    result['correction'] = {'kind': 'deterministic_evidence_correction',
                            'prior_result_sha256': snapshot['original_sha256'],
                            'release_receipt_sha256': snapshot['receipt_sha256'],
                            'evidence_id': release_ref}
    for field in ('share_token', 'notify', '_notify_started'):
        result.pop(field, None)
    result['body'] = report_body(result['facts'], analysis)
    result['notification_body'] = notification_digest(result['facts'], analysis,
                                                      observed_at=at, revision=2)
    require(all(term not in result['body'] for term in
                ('前置校验为何', '按计划跌破452', '09:30失败作废', '连续第三日',
                 '第三种失效形态', 'deferred可延续9/22已核实',
                 '58-59滞涨则按合同了结', 'DEPLOYMENT.json')),
            '更正正文仍包含错误归因')
    require(len(result['facts']['trades']) == 8 and result['facts']['period_pnl_cents'] == -648,
            '更正不得修改成交和盈亏')
    return result, edits


def make_old_candidate(snapshot: dict, *, at: str) -> tuple[dict, list[str]]:
    result = deepcopy(snapshot['old_report'])
    analysis, edits = revise_old_analysis(result['analysis'])
    result['analysis'] = analysis
    result['facts']['correction_reason'] = OLD_REASON
    result['revision'] = 4
    result['created_at'] = at
    result['correction'] = {'kind': 'deterministic_evidence_correction',
                            'prior_result_sha256': snapshot['old_sha256']}
    for field in ('share_token', 'notify', '_notify_started'):
        result.pop(field, None)
    result['body'] = report_body(result['facts'], analysis)
    result['notification_body'] = notification_digest(result['facts'], analysis,
                                                      observed_at=at, revision=4)
    require('failed后作废' not in result['body'] and '导致5笔开盘建仓' not in result['body'],
            '9/21 更正正文仍有错误归因')
    require(result['facts']['period_pnl_cents'] == 77023 and analysis['experience'] is None,
            '9/21 更正不得修改账务或覆盖新经验')
    return result, edits


def backup_ledger(db: Path, backup: Path) -> None:
    require(not backup.exists() and backup.resolve() != db.resolve(), '备份目标已存在或等于原库')
    require(backup.parent.is_dir(), '备份目录不存在')
    source = sqlite3.connect(f'file:{db.as_posix()}?mode=ro', uri=True)
    try:
        target = sqlite3.connect(backup)
        try:
            source.backup(target)
            require(target.execute('PRAGMA quick_check').fetchone()[0] == 'ok', '备份 quick_check 失败')
        finally:
            target.close()
    finally:
        source.close()


def apply_atomic_batch(db: Path, snapshot: dict, current: dict, historical: dict) -> None:
    """Mirror report revision rows while keeping every write in one transaction."""
    with GuardianStore(db) as ledger:
        conn = ledger.conn
        conn.execute('BEGIN IMMEDIATE')
        try:
            originals = {}
            for key, revision, expected in ((KEY, 1, snapshot['original_sha256']),
                                            (OLD_KEY, 3, snapshot['old_sha256'])):
                row = conn.execute('SELECT status,result_json FROM guardian_reports WHERE report_key=?',
                                   (key,)).fetchone()
                require(row is not None and row['status'] == 'success'
                        and sha256(row['result_json'].encode('utf-8')).hexdigest() == expected,
                        f'{key} 在备份后变化，整批拒绝')
                require(json.loads(row['result_json'])['revision'] == revision,
                        f'{key} 当前版本变化')
                require(conn.execute('SELECT count(*) FROM guardian_report_revisions '
                                     'WHERE report_key=? AND revision=?', (key, revision)).fetchone()[0] == 0,
                        f'{key} 旧版已归档，拒绝重复更正')
                originals[key] = row['result_json']
            middle = conn.execute("SELECT status,result_json FROM guardian_reports "
                                  "WHERE report_key='daily:2026-09-22'").fetchone()
            require(middle is not None and middle['status'] == 'success'
                    and sha256(middle['result_json'].encode('utf-8')).hexdigest() == snapshot['middle_sha256'],
                    '9/22 证据报告在备份后变化')
            experience = conn.execute('SELECT revision,source_report,source_revision FROM '
                                      'guardian_experience_versions ORDER BY revision DESC LIMIT 1').fetchone()
            require(experience is not None and tuple(experience) == (7, KEY, 1),
                    '最新经验在备份后变化')
            require(conn.execute('SELECT state_json FROM guardian_portfolio WHERE id=1').fetchone()[0]
                    == snapshot['portfolio_before'], '账户或观察名单在备份后变化')
            require(table_digest(conn, 'guardian_trades', 'id,slot,code,occurred_at,detail_json')
                    == snapshot['trade_digest'], '交易流水在备份后变化')
            require(table_digest(conn, 'guardian_cycles', 'slot,started,status,result_json')
                    == snapshot['cycle_digest'], '轮次在备份后变化')

            now = time.time()
            for key, revision, reason, candidate in ((KEY, 1, REASON, current),
                                                      (OLD_KEY, 3, OLD_REASON, historical)):
                require(candidate.get('status') == 'success'
                        and candidate.get('revision') == revision + 1
                        and candidate.get('facts', {}).get('correction_reason') == reason,
                        f'{key} 更正版本或原因与归档不一致')
                require(not candidate.get('notify') and not candidate.get('share_token'),
                        f'{key} 仍带旧通知或旧分享地址')
                if key == OLD_KEY:
                    require(candidate['analysis'].get('experience') is None,
                            '9/21 历史更正不得回写经验')
                conn.execute('INSERT INTO guardian_report_revisions '
                             '(report_key,revision,reason,archived_at,result_json) VALUES(?,?,?,?,?)',
                             (key, revision, reason, now, originals[key]))
                changed = conn.execute("UPDATE guardian_reports SET status='success',token='',"
                                       'started=?,result_json=? WHERE report_key=? AND status=\'success\'',
                                       (now, json.dumps(candidate, ensure_ascii=False), key))
                require(changed.rowcount == 1, f'{key} 更正写入失败')

            # Only the 9/23 correction advances current experience. The older
            # 9/21 report keeps experience=None and cannot overwrite rev8.
            ledger._save_experience(current['analysis']['experience'], source_report=KEY,
                                    source_revision=2, day=DAY, expected_revision=7)
            require(ledger.experience()['revision'] == 8, '经验 rev8 未在批次内生成')
            for key, revision in ((KEY, 2), (OLD_KEY, 4)):
                saved = conn.execute('SELECT status,result_json FROM guardian_reports WHERE report_key=?',
                                     (key,)).fetchone()
                require(saved is not None and saved['status'] == 'success'
                        and json.loads(saved['result_json'])['revision'] == revision,
                        f'{key} 更正版本未保存')
            require(conn.execute('SELECT state_json FROM guardian_portfolio WHERE id=1').fetchone()[0]
                    == snapshot['portfolio_before'], '更正修改了账户或观察名单')
            require(table_digest(conn, 'guardian_trades', 'id,slot,code,occurred_at,detail_json')
                    == snapshot['trade_digest'], '更正修改了交易流水')
            require(table_digest(conn, 'guardian_cycles', 'slot,started,status,result_json')
                    == snapshot['cycle_digest'], '更正修改了轮次')
            for key, revision, expected in ((KEY, 1, snapshot['original_sha256']),
                                            (OLD_KEY, 3, snapshot['old_sha256'])):
                archived = conn.execute('SELECT result_json FROM guardian_report_revisions '
                                        'WHERE report_key=? AND revision=?', (key, revision)).fetchone()
                require(archived is not None
                        and sha256(archived['result_json'].encode('utf-8')).hexdigest() == expected,
                        f'{key} 旧版归档不完整')
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path, help='explicit palace.db path')
    parser.add_argument('--receipt', required=True, type=Path, help='guardian-deadline DEPLOYMENT.json')
    parser.add_argument('--apply', action='store_true', help='one atomic batch: 9/23 rev2, 9/21 rev4, experience rev8')
    parser.add_argument('--backup', type=Path, help='required new SQLite backup file when applying')
    args = parser.parse_args()
    if args.apply:
        require(args.backup is not None, '--apply 必须指定新的 --backup 路径')
    snapshot = read_snapshot(args.db, args.receipt)
    at = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
    candidate, edits = make_candidate(snapshot, at=at)
    old_candidate, old_edits = make_old_candidate(snapshot, at=at)
    preview = {'mode': 'apply' if args.apply else 'dry-run', 'report_key': KEY,
               'from_revision': 1, 'to_revision': 2, 'experience_from': 7, 'experience_to': 8,
               'original_sha256': snapshot['original_sha256'], 'changed_analysis_fields': edits,
               'summary': candidate['analysis']['summary'],
               'historical_report': {'report_key': OLD_KEY, 'from_revision': 3, 'to_revision': 4,
                                     'original_sha256': snapshot['old_sha256'],
                                     'changed_analysis_fields': old_edits,
                                     'summary': old_candidate['analysis']['summary'],
                                     'experience_update': None},
               'board_eligibility': next(x for x in candidate['analysis']['experience']
                                         if x['id'] == 'board_eligibility')}
    if not args.apply:
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return
    backup_ledger(args.db, args.backup)
    apply_atomic_batch(args.db, snapshot, candidate, old_candidate)
    print(json.dumps({**preview, 'backup': str(args.backup), 'saved': True}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
