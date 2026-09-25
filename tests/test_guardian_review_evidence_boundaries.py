"""Regression cases taken from the September 23 review's historical and contract claims."""

import json

import pytest

from src.ops.application.guardian_review_agent import (
    validate_contract_plan_claims,
    validate_cross_day_verified_claims,
    validate_experience_update,
    validate_historical_board_claims,
    validate_prior_auction_handoff_claims,
)
from src.ops.application.guardian_review_prompts import review_system


def _historical_facts(*, restricted_at_trade=False):
    policy = ({"buyable_code_prefixes": ["600", "300"]} if restricted_at_trade
              else {"position_count": 3, "locked_codes": [], "locked_count": 0})
    return {
        "period": "daily", "trade_date": "2026-09-23",
        "current_position_policy": {"as_of": "2026-09-23T16:10:00+08:00",
                                    "buyable_code_prefixes": ["600", "300"]},
        "trades": [{"code": "688825", "side": "buy"}, {"code": "688825", "side": "buy"}],
        "cycles": [
            {"id": "cycle:09:40", "slot": "2026-09-23T09:40:00+08:00",
             "position_policy": policy, "fills": [{"code": "688825", "side": "buy"}]},
            {"id": "cycle:09:55", "slot": "2026-09-23T09:55:00+08:00",
             "position_policy": policy, "fills": [{"code": "688825", "side": "buy"}]},
        ],
        "experience": {"items": []},
    }


def test_retrospective_does_not_inject_current_buy_restriction():
    retrospective = review_system({}, "daily", {}, stage="retrospective")
    planning = review_system({}, "daily", {}, stage="planning")
    assert "禁止买入或加仓科创板" not in retrospective
    assert "不能倒推历史成交时已有同一权限" in retrospective
    assert "prior_auction_cycles" in retrospective
    assert "禁止买入或加仓科创板" in planning


def test_report_cannot_call_pre_rule_star_fills_a_guard_failure():
    facts = _historical_facts()
    claim = {"summary": "长鑫科技为688科创板，本账户不可买入却成交400股，需核查拦截环节。"}
    with pytest.raises(ValueError, match="缺少对应轮次的禁买规则快照"):
        validate_historical_board_claims(claim, facts)
    with pytest.raises(ValueError, match="缺少对应轮次的禁买规则快照"):
        validate_historical_board_claims({"lessons": [{"hypothesis": "688825买入前置校验未按板块拦截"}]}, facts)
    validate_historical_board_claims({"summary": "两笔688825成交时的板块权限未记录；现行规则禁止继续加仓。"}, facts)
    validate_historical_board_claims(claim, _historical_facts(restricted_at_trade=True))


@pytest.mark.parametrize('section,text', [
    ('summary', '长鑫科技为688科创板，本账户不可买入却成交400股，持仓按账本保留、不得再加、需核查拦截环节。'),
    ('assessments', '科创板执行冲突：688825长鑫科技属688科创板，本账户可买板块仅沪深主板与创业板，但09:42买200股、09:57加200股共400股成交；需核验买入前置校验为何未按板块拦截。'),
    ('operational_notes', '688825两笔买入未被板块校验拦截：账户可买板块为沪深主板与创业板，但09:42与09:57两笔成交。'),
    ('experience', '账户可买板块为沪深主板与创业板，688/689不在其中；9/23两笔688825买入成交400股，买入前置板块校验未拦截。'),
])
def test_original_report_wording_is_rejected_in_each_field(section, text):
    analysis = ({section: text} if section == 'summary' else
                {section: [{'hypothesis': text}]} if section == 'experience' else
                {section: [text]})
    with pytest.raises(ValueError, match="缺少对应轮次的禁买规则快照"):
        validate_historical_board_claims(analysis, _historical_facts())


def test_false_existing_experience_requires_correction_instead_of_null():
    facts = _historical_facts()
    facts["experience"] = {"items": [{"id": "board_eligibility", "status": "corrected",
        "hypothesis": "9/23两笔688825成交，说明买入前置板块校验未拦截。",
        "validation_plan": "检查前置校验", "evidence_ids": ["trade:one", "trade:two"]}]}
    with pytest.raises(ValueError, match="本次须输出更正后的完整经验列表"):
        validate_experience_update({"experience": None}, facts, set())
    validate_experience_update({"experience": []}, facts, set())


def test_prior_day_verified_cause_needs_original_cycle_receipt():
    facts = {"trade_date": "2026-09-23", "prior_auction_cycles": [
        {"id": "cycle:2026-09-22T09:25:00+08:00", "slot": "2026-09-22T09:25:00+08:00", "status": "success"}]}
    claim = {"lessons": [{"status": "corrected", "hypothesis": "9/22竞价轮次的原因已核实",
                          "evidence_ids": ["daily:2026-09-22"]}]}
    with pytest.raises(ValueError, match="原始轮次回执引用"):
        validate_cross_day_verified_claims(claim, facts, [])
    claim["lessons"][0]["evidence_ids"] = ["cycle:2026-09-22T09:25:00+08:00"]
    validate_cross_day_verified_claims(claim, facts, [])


def test_prior_day_tool_receipt_must_contain_original_cycle():
    facts = {"trade_date": "2026-09-23"}
    claim = {"lessons": [{"status": "corrected", "hypothesis": "9/22竞价超时原因已核实",
                          "evidence_ids": ["tool:1"]}]}
    receipt = {"id": "tool:1", "name": "guardian_decision_history", "arguments": {"date": "2026-09-22"},
               "is_error": False, "result": json.dumps({"items": []})}
    with pytest.raises(ValueError, match="原始轮次回执引用"):
        validate_cross_day_verified_claims(claim, facts, [receipt])
    receipt["result"] = json.dumps({"items": [{"slot": "2026-09-22T09:25:00+08:00"}]})
    validate_cross_day_verified_claims(claim, facts, [receipt])


def test_auction_handoff_cause_needs_both_original_cycles():
    facts = {"trade_date": "2026-09-23", "prior_auction_cycles": [
        {"id": f"cycle:2026-09-21T{slot}:00+08:00", "slot": f"2026-09-21T{slot}:00+08:00"}
        for slot in ("09:25", "09:30")]}
    claim = {"lessons": [{"status": "corrected",
                          "hypothesis": "9/21 09:25计划因09:30轮次失败作废，已核实",
                          "evidence_ids": ["cycle:2026-09-21T09:25:00+08:00"]}]}
    with pytest.raises(ValueError, match="同时引用09:25和09:30"):
        validate_cross_day_verified_claims(claim, facts, [])
    claim["lessons"][0]["evidence_ids"].append("cycle:2026-09-21T09:30:00+08:00")
    validate_cross_day_verified_claims(claim, facts, [])


def test_auction_zero_saved_plans_refutes_failure_caused_void_even_with_both_ids():
    facts = {"trade_date": "2026-09-23", "prior_auction_cycles": [
        {"id": "cycle:2026-09-21T09:25:00+08:00", "slot": "2026-09-21T09:25:00+08:00",
         "status": "success", "deferred": 5, "opening_plans": 0},
        {"id": "cycle:2026-09-21T09:30:00+08:00", "slot": "2026-09-21T09:30:00+08:00",
         "status": "failed", "opening_plans": 0},
    ]}
    wrong = "9/21 09:25的deferred因09:30失败作废"
    refs = [row['id'] for row in facts['prior_auction_cycles']]
    with pytest.raises(ValueError, match="没有保存opening_plans"):
        validate_prior_auction_handoff_claims({"experience": [{"hypothesis": wrong}]}, facts)
    with pytest.raises(ValueError, match="没有保存opening_plans"):
        validate_experience_update({"experience": [{"id": "auction", "hypothesis": wrong,
            "validation_plan": "回读轮次", "status": "corrected", "evidence_ids": refs}]},
            {**facts, "period": "daily", "experience": {"items": []}}, set(refs))
    validate_prior_auction_handoff_claims(
        {"summary": "9/21 09:25的deferred未形成opening_plans，不能因09:30失败作废。"}, facts)


def test_plan_cannot_describe_58_to_59_as_installed_59_5_trigger():
    facts = {"risk_contracts": {"available": True, "positions": [{"code": "601208", "risk_plans": [
        {"status": "active", "contract": {"action": "take_profit", "quantity": 800,
                                           "trigger_price": 59.5}}]}]}}
    plan = {"code": "601208", "action": "hold", "rationale": "等待冲高", "invalidation": "",
            "trigger": "若冲至58-59滞涨则按合同了结。"}
    with pytest.raises(ValueError, match="有效合同无此触发价"):
        validate_contract_plan_claims({"plans": [plan]}, facts)
    plan["trigger"] = "若冲至58-59滞涨，盘中重新研判是否卖出；触及59.5则按合同了结。"
    validate_contract_plan_claims({"plans": [plan]}, facts)


@pytest.mark.parametrize('denial', ['不能判', '不能认定', '无法证明', '不能因', '不会因', '并非因'])
def test_auction_causal_denial_is_not_an_affirmative_claim(denial):
    facts = {'trade_date': '2026-09-24', 'prior_auction_cycles': [
        {'slot': '2026-09-21T09:25:00+08:00', 'opening_plans': 0}]}
    validate_prior_auction_handoff_claims({'summary':
        f'9/21 09:25的deferred未形成预案，故{denial}09:30失败致其作废。'}, facts)


def test_auction_denial_does_not_exempt_later_false_assertion():
    facts = {'trade_date': '2026-09-24', 'prior_auction_cycles': [
        {'slot': '2026-09-21T09:25:00+08:00', 'opening_plans': 0}]}
    with pytest.raises(ValueError, match='2026-09-21'):
        validate_prior_auction_handoff_claims({'summary':
            '9/21竞价意图不能因09:30失败作废，但实际09:30失败使意图作废。'}, facts)


def test_auction_cause_is_not_assigned_to_another_day_in_same_paragraph():
    facts = {'trade_date': '2026-09-24', 'prior_auction_cycles': [
        {'slot': '2026-09-21T09:25:00+08:00', 'opening_plans': 2},
        {'slot': '2026-09-23T09:25:00+08:00', 'opening_plans': 0}]}
    validate_prior_auction_handoff_claims({'summary':
        '9/21 09:25预案因09:30失败作废。9/23 09:25研究超时，0决策0意图。'}, facts)


def test_production_mixed_day_correction_needs_only_the_cycles_it_describes():
    facts = {'trade_date': '2026-09-24', 'prior_auction_cycles': [
        {'id': f'cycle:{day}T{slot}:00+08:00', 'slot': f'{day}T{slot}:00+08:00',
         'opening_plans': 2 if day == '2026-09-22' else 0}
        for day in ('2026-09-21', '2026-09-22', '2026-09-23') for slot in ('09:25', '09:30')]}
    refs = [r['id'] for r in facts['prior_auction_cycles'] if r['slot'] != '2026-09-23T09:30:00+08:00']
    claim = {'experience': [{'status': 'corrected', 'evidence_ids': refs, 'hypothesis':
        '9/21原始回执：09:25轮success、5笔买单记为deferred；09:30轮failed，'
        '5笔买单无逐笔接续或到期回执，故不能判09:30失败致其作废。'
        '9/22两轮成对：09:25轮记录2笔开盘预案，09:30轮逐笔复核。'
        '9/23 09:25轮failed(研究超270秒、0决策0意图)属另一形态；'
        '9/24 09:25轮success、0 opening_plans。'}]}
    validate_prior_auction_handoff_claims(claim, facts)
    validate_cross_day_verified_claims(claim, facts, [])
    claim['experience'][0]['evidence_ids'].remove('cycle:2026-09-22T09:30:00+08:00')
    with pytest.raises(ValueError, match='2026-09-22竞价到开盘'):
        validate_cross_day_verified_claims(claim, facts, [])


@pytest.mark.parametrize('tool', ['guardian_decision_history', 'guardian_review_history'])
def test_paired_auction_receipts_can_be_cited_through_history_tool(tool):
    rows = [{'id': f'cycle:2026-09-21T{time}:00+08:00',
             'slot': f'2026-09-21T{time}:00+08:00'} for time in ('09:25', '09:30')]
    facts = {'trade_date': '2026-09-24', 'prior_auction_cycles': rows}
    claim = {'experience': [{'status': 'corrected', 'evidence_ids': ['tool:1'],
                            'hypothesis': '9/21 09:25与09:30原始回执已核实。'}]}
    def receipt(items):
        body = items if tool == 'guardian_decision_history' else [
            {'date': '2026-09-21', 'facts': {'cycles': items}}]
        return {'id': 'tool:1', 'name': tool, 'arguments': {'date': '2026-09-21', 'fields': ['facts']},
                'result': json.dumps({'items': body}), 'is_error': False}
    validate_cross_day_verified_claims(claim, facts, [receipt(rows)])
    with pytest.raises(ValueError, match='同时引用09:25和09:30'):
        validate_cross_day_verified_claims(claim, facts, [receipt(rows[:1])])
    with pytest.raises(ValueError, match='原始轮次回执引用'):
        validate_cross_day_verified_claims(claim, facts, [{**receipt(rows), 'is_error': True}])


def test_experience_repair_receives_evidence_and_size_errors_together():
    items = [{'id': f'item{i}', 'status': 'corrected',
              'hypothesis': '9/21竞价原因已核实。' + '待核验的研究边界' * 30,
              'validation_plan': '按原始轮次复核', 'evidence_ids': ['daily:2026-09-21']}
             for i in range(6)]
    facts = {'period': 'daily', 'trade_date': '2026-09-24', 'experience': {'items': []}}
    with pytest.raises(ValueError) as caught:
        validate_experience_update({'experience': items}, facts, {'daily:2026-09-21'})
    assert '原始轮次回执引用' in str(caught.value)
    assert '最多1600字符' in str(caught.value)
    assert '当前实际' in str(caught.value)
    assert '超出' in str(caught.value)


def test_malformed_experience_still_returns_repairable_validation_error():
    with pytest.raises(ValueError):
        validate_experience_update({'experience': [{'hypothesis': '待验证'}]},
                                   {'period': 'daily', 'experience': {'items': []}}, set())


def test_corrected_market_high_reference_does_not_require_an_account_cycle():
    analysis = {'lessons': [{'status': 'corrected', 'evidence_ids': ['tool:kline'],
        'hypothesis': '买入理由称12日区间内放量突破，但当日高点未越过上沿，'
                      '突破只对近6日高点（9/21的22.98）成立；此前提当日未发生。'}]}
    validate_cross_day_verified_claims(analysis, {'trade_date': '2026-09-24'}, [])
    analysis['lessons'][0]['hypothesis'] = '9/21买入成交原因已核实。'
    with pytest.raises(ValueError, match='原始轮次回执引用'):
        validate_cross_day_verified_claims(analysis, {'trade_date': '2026-09-24'}, [])
