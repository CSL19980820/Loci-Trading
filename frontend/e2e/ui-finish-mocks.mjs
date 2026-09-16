/** Synthetic UI fixtures only. No real quotes, accounts, credentials or model calls. */
import { auditPayloadFor } from './audit-mocks.mjs'

const profile = {
  about_user: '界面验收用的测试用户。', response_style: '先列结论，再列依据。',
  rules: ['区分已确认事实与尚待验证的假设。'],
  memory_enabled: true, auto_memory_enabled: true, auto_memory_min_turns: 20,
  memory_usage: { user: 0, memory: 0 },
}
const provider = {
  name: '界面测试模型', models: ['ui-fixture-model-with-a-long-version-name'],
  default_model: 'ui-fixture-model-with-a-long-version-name', is_active: true, is_default: true,
}
const session = {
  id: 'ui-fixture', title: '策略复盘与数据核对 · 仅供界面验收', status: 'done',
  provider: provider.name, model: provider.default_model, updated_at: '2026-08-27T10:42:00',
}
const messages = [
  { id: 'ui-user', role: 'user', content: '请核对策略的数据来源、执行口径和待验证问题。', status: 'done' },
  {
    id: 'ui-answer', role: 'assistant', status: 'done',
    content: '## 验收示例，不是投资建议\n\n已完成界面测试数据的核对。以下内容仅用于检查长文本、表格和代码块的排版。\n\n| 核对项目 | 状态 | 说明 |\n| --- | --- | --- |\n| 数据来源 | 已核对 | 保留原始来源与采集时间 |\n| 复盘口径 | 待确认 | 区分信号表现与真实成交 |\n\n```python\n# 长行应在代码块内部横向滚动，不挤压整个会话\nprint("ui_fixture_abcdefghijklmnopqrstuvwxyz_abcdefghijklmnopqrstuvwxyz_abcdefghijklmnopqrstuvwxyz")\n```\n\n待办：复核数据的新鲜度，并查看回测成本参数。',
    tool_receipts: [{ call_id: 'ui-check', name: 'market.coverage', status: 'done', summary: '测试数据核对完成', elapsed_ms: 250 }],
  },
]
const horizon = {
  n: 48, win_rate: 62.5, avg: 1.8, best: 8.2, worst: -5.6, median: 1.4, std: 3.1,
  avg_win: 3.8, avg_loss: -1.53, payoff_ratio: 2.48, close_n: 48, close_avg: 0.9,
  close_median: 0.6, close_win_rate: 56.25, close_best: 6.1, close_worst: -6.4,
  sample_confidence: 'medium', caution: '仅供界面验收',
  distribution: [{ lo: -6, hi: -3, n: 5 }, { lo: -3, hi: 0, n: 13 }, { lo: 0, hi: 3, n: 20 }, { lo: 3, hi: 9, n: 10 }],
  by_month: [{ period: '2026-07', n: 24, win_rate: 62.5, avg: 1.8 }, { period: '2026-08', n: 24, win_rate: 62.5, avg: 1.8 }],
}
const trade = {
  strategy: 'ui-fixture', mode: 'trade', config: {}, skipped: {},
  metrics: { trades: 2, wins: 1, losses: 1, win_rate: 50, avg_net_return: 1.2, best: 4, worst: -1.6, caution: '仅供界面验收', exit_reasons: { hold_days: 2 } },
  performance: {
    available: true, cumulative_return_pct: 2.336, max_drawdown_pct: -1.6, final_equity: 1.02336,
    equity_curve: [ { date: '2026-08-24', equity: 1, drawdown_pct: 0 }, { date: '2026-08-25', equity: 1.04, drawdown_pct: 0 }, { date: '2026-08-26', equity: 1.02336, drawdown_pct: -1.6 } ],
    drawdown_curve: [ { date: '2026-08-24', drawdown_pct: 0 }, { date: '2026-08-25', drawdown_pct: 0 }, { date: '2026-08-26', drawdown_pct: -1.6 } ],
  },
  trades: [4, -1.6].map((ret, i) => ({ code: i ? '600519' : '000001', signal_date: '2026-08-20', entry_date: '2026-08-21', entry_price: 10, exit_date: `2026-08-${25 + i}`, exit_price: 10 * (1 + ret / 100), hold_days: 3, gross_return_pct: ret, net_return_pct: ret, mae_pct: -2, mfe_pct: 5, exit_reason: 'hold_days', benchmark_return_pct: null, alpha_pct: null })),
}

export function uiPayloadFor(url, scene, request = {}) {
  const path = new URL(url).pathname
  if (path.endsWith('/ai/tools')) return { provider_configured: true, providers: [provider], tools: [], system_prompt_tokens: 100 }
  if (path.endsWith('/ai/profile')) return profile
  if (path.endsWith('/ai/memories')) return []
  if (path.endsWith('/ai/sessions')) return scene === 'assistant-empty' ? [] : [session]
  if (path.endsWith('/ai/sessions/ui-fixture')) return { ...session, messages, active_run: null }
  if (path.endsWith('/backtest')) return request.mode === 'trade' ? trade : { strategy: 'ui-fixture', mode: 'horizon', entry_timing: 'next_open', config: {}, horizons: { t1: horizon, t3: horizon }, skipped: {} }
  if (path.endsWith('/screen-skills/preview')) return { ok: true, diagnostics: [], runtime: 'formula', dialect: 'tdx', explanation: null, run_result: null }
  if (path.endsWith('/market/coverage')) return { rows: 20000, codes: 100, first_date: '2025-01-02', last_date: '2026-08-26', failed_codes: 0, db_path: '', db_bytes: 0 }
  return auditPayloadFor(url)
}
