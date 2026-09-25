const user = { id: 'smoke-admin', tenant_id: '__smoke__', username: 'smokeadmin', display_name: '隔离验收管理员', role: 'admin', status: 'active', email: 'smoke@example.invalid', avatar_url: '', bio: '', must_change_password: false }
const quota = { llm_monthly_tokens: 100000, llm_daily_calls: 100, strategy_slots: 20, publish_slots: 10, job_slots: 10 }
const config = { name: '隔离验收智能体', kind: 'custom', description: '浏览器夹具，不执行交易', provider: '', model: '', prompt: '', enabled: false, initial_capital_cents: 10000000, strategies: [], daily_selection_limit: 5, watch_limit: 10, position_limit: 3, temporary_position_limit: 0, max_position_pct: 30, timeout_seconds: 60, retention: { days: 30, max_entries: 100, cleanup_hours: 24 }, schedule: { timezone: 'Asia/Shanghai', review_time: '15:10', premarket_time: '08:30', auction_time: '09:25', intraday_minutes: 15, intraday_enabled: false } }
const state = { initial_capital_cents: 10000000, equity_cents: 10000000, cash_cents: 10000000, market_value_cents: 0, total_pnl_cents: 0, realized_pnl_cents: 0, unrealized_pnl_cents: 0, fees_cents: 0, positions: [], watchlist: [], stale_codes: [], experience: [], valuation_at: '', selected_today: { date: '2026-09-22', codes: [] } }
const agent = { id: 'smoke-agent', revision: 1, state_version: 1, config, state, archived: false, running: false, created_at: '2026-09-22T00:00:00Z', updated_at: '2026-09-22T00:00:00Z', total_runs: 0, total_actions: 0, total_trades: 0, cleaned_runs: 0, history_kept: 0, latest_at: null, latest_phase: null, latest_status: null, latest_summary: '', latest_actions: [], schedules: [] }
const emptyPage = { items: [], total: 0, offset: 0, limit: 20 }
const coverage = { rows: 0, codes: 0, first_date: '', last_date: '', failed_codes: 0, db_path: 'isolated-fixture', db_bytes: 0 }
const session = { today: '2026-09-22', now: '2026-09-22T16:00:00+08:00', is_trading_day: true, last_trading_day: '2026-09-22', expected_last_date: '2026-09-22', coverage_first_date: null, coverage_last_date: null, coverage_rows: 0, db_is_current: true, lag_trading_days: 0, needs_backfill: false, backfill_kind: 'none', backfill_from: null, backfill_to: null, live_allowed: false, live_reason: 'after_close', in_live_clock: false }
export function routeFixture(url, scenario) {
  const p = url.pathname.replace(/^\/api/, '')
  const ok = body => ({ body })
  if (p === '/auth/session') return ok({ authenticated: scenario !== 'login', username: user.username, user: scenario === 'login' ? null : user })
  if (p === '/auth/me') return ok({ user, quota, identities: [], sessions: [], usage: {} })
  if (p === '/auth/options') return ok({ email_signup: false, providers: [{ name: 'mock', family: 'mock', label: '隔离扫码通道', mode: 'qrcode' }] })
  if (p === '/market/bootstrap') return ok({ status: 'idle', phase: '', done: 0, total: 0, percent: 0, code: '', message: '', needed: false, coverage, session })
  if (p === '/market/session') return ok(session)
  if (p === '/market/coverage') return ok(coverage)
  if (p === '/market/live-tape') return ok({ indices: [], items: [], as_of: '', leaders: [], sectors: [] })
  if (p === '/market/board') return ok({ ...emptyPage, as_of: '', page: 1, page_size: 40 })
  if (['/skills', '/strategies', '/providers', '/mcp', '/jobs', '/jobs/runs', '/market/industries', '/screen-skills', '/ops/alert-rules'].includes(p)) return ok([])
  if (p === '/candidates/list') return ok([])
  if (p === '/jobs/schedule') return ok({ running: false, reason: '隔离验收', jobs: [] })
  if (p === '/jobs/quota') return ok({ used: 0, limit: 20, unlimited: false, managed: 0 })
  if (p === '/mcp/quota') return ok({ trade_date: '2026-09-22', limits: { daily_total: 100, structured: 50, skill: 50, per_minute: 10 }, used: { total: 0, structured: 0, skill: 0 }, remaining: { total: 100, structured: 50, skill: 50 } })
  if (p === '/ops/lanes') return ok({ lanes: [], providers: [], policies: [], summary: { ok: 0, degraded: 0, down: 0 } })
  if (p === '/market/akshare/sources') return ok({ sources: [], total: 0, akshare_version: '' })
  if (p === '/market/quotes/000001') return ok({ code: '000001', name: '隔离样本', adjust: 'qfq', rows: 0, bars: [] })
  if (['/universe/presets', '/winrate/summary', '/insights/decay'].includes(p)) return ok([])
  if (p === '/universe/stats') return ok({ total: 0, by_board: {}, st_count: 0, selectable_default: 0, bse_blocked: true, as_of: '' })
  if (p === '/screen-skills/catalog') return ok({ runtimes: [], dialects: [], fields: [], functions: [], snippets: [] })
  if (p === '/research/catalog') return ok({ version: 'smoke', dimensions: [], sources: [], market_adapters: [], quality_values: [], budgets: [], guardrails: { production_signal: false, static_scores_are_not_facts: true, missing_data_stays_missing: true, market_health_gate: true } })
  if (p === '/research/backtest-runs' || p === '/research/hypotheses') return ok(emptyPage)
  if (p === '/skills/demo/leader-roles') return ok({ slug: 'demo', history: [], transitions: [], suggestions: [] })
  if (p === '/review/candidates') return ok({ outcomes: [], summary: { total: 0, wins: 0, losses: 0, pending: 0, win_rate: null } })
  if (p === '/intel/brief') return ok({ trade_date: '2026-09-22', available: false, fetched_at: null, emotion: null, themes: [], ladder: null, tools: {}, source: 'intel_snapshots', optional: true, note: '隔离空态' })
  if (p === '/ops/market-sync') return ok({ enabled_intraday: false, interval_minutes: 5, enabled_eod: false, eod_hour: 16, eod_minute: 0, workers: 1, push_wecom_on_fail: false })
  if (p === '/ops/settings/retention') return ok({ policy: { enabled: false }, revision: 1, global_scope: true, jobs: [] })
  if (p === '/ops/stock-agents/guardian/storage') return ok({ total_runs: 0, full_entries: 0, compacted_entries: 0, total_trades: 0, total_reports: 0, retention: config.retention, protected_recent: 0 })
  if (p === '/screen/run') return ok({ status: 'idle', running: false, items: [], total: 0 })
  if (p === '/ops/settings/notify') return ok({ quiet_hours: '', timezone: 'Asia/Shanghai', bark: { enabled: false, device_key: '', server_url: '' }, channels: [] })
  if (p === '/ops/settings/wecom') return ok({ configured: false, url_masked: '', preview: '' })
  if (p === '/ops/paper-cabins/demo') return ok({ cabin: {}, positions: [], fills: [], monitor_runs: [], nextday_plan: null })
  if (p === '/ops/stock-agents/smoke-agent') return ok(agent)
  if (p === '/ops/stock-agents/options') return ok({ templates: { custom: config, leader: config }, strategies: [], timezone: 'Asia/Shanghai' })
  if (p === '/ops/stock-agents/smoke-agent/equity') return ok({ items: [], total: 0, truncated: false, caliber: '隔离数据' })
  if (p === '/ops/stock-agents/smoke-agent/history') return ok(emptyPage)
  if (p === '/ops/stock-agents') return ok({ items: [], as_of: '2026-09-22T00:00:00Z' })
  if (p === '/ops/stock-agents/guardian/overview') return ok({ config, state, runs: [], position_count: 0, stats: { total_runs: 0, full_entries: 0, compacted_entries: 0, total_trades: 0, total_reports: 0, retention: config.retention, protected_recent: 0 }, position_policy: { normal_max: 3, absolute_max: 5, close_max: 3 } })
  if (p === '/admin/users') return ok(emptyPage)
  if (p === '/admin/audit' || p === '/admin/logins') return ok(emptyPage)
  if (p === '/admin/overview') return ok({ users: 0, admins: 0, visitors: 0, tenants: [], top_llm_usage: [], recent_audit: [] })
  if (p === '/admin/llm-usage') return ok({ items: [], unavailable_tenants: [] })
  if (p === '/ops/llm/providers' || p === '/quant/strategies' || p === '/ops/jobs' || p === '/market/search') return ok([])
  if (p === '/ops/guardian/activity') return ok({ runs: [], reports: [], limit: 16 })
  return null
}
