/**
 * 盘面视觉自查用的 /api mock 数据（供 pulse-shots / pulse-metrics 共用）。
 *
 * 路由匹配必须按 pathname 判断：dev 下 `**\/api/**` 会连 `/src/shared/api/palace.ts`
 * 这类源码模块一起劫持，页面会因为 MIME 变 JSON 而整页白。
 */
export const API_MATCH = (url) => new URL(url).pathname.startsWith('/api/')

const TODAY = '2026-08-27'
/** 冻结到早盘 10:42，刻度尺才有刻针与半程填充可看 */
export const FIXED_NOW = new Date(2026, 7, 27, 10, 42, 5)
const NOW = `${TODAY} 10:42:05`

const user = {
  id: 'u1',
  username: 'shot',
  display_name: '自查用户',
  avatar_url: '',
  bio: '',
  role: 'member',
  created_at: '2026-01-01T00:00:00',
  email: 'shot@example.com',
  email_verified: true,
  status: 'active',
  must_change_password: false,
  has_password: true,
}
const session = {
  today: TODAY,
  now: NOW,
  is_trading_day: true,
  last_trading_day: TODAY,
  expected_last_date: '2026-08-26',
  coverage_first_date: '2020-01-02',
  coverage_last_date: '2026-08-26',
  coverage_rows: 8123456,
  db_is_current: true,
  lag_trading_days: 0,
  needs_backfill: false,
  backfill_kind: 'none',
  backfill_from: null,
  backfill_to: null,
  live_allowed: true,
  live_reason: 'live_window',
  in_live_clock: true,
}

const tape = {
  as_of: NOW,
  source: 'mock',
  error: '',
  title: '指数',
  indices: [
    { code: '000001', label: '上证指数', name: '上证指数', kind: 'index', price: 3421.55, pct: 0.82 },
    { code: '399001', label: '深证成指', name: '深证成指', kind: 'index', price: 10832.1, pct: -0.31 },
    { code: '399006', label: '创业板指', name: '创业板指', kind: 'index', price: 2210.4, pct: 1.2 },
    { code: '000688', label: '科创50', name: '科创 50', kind: 'index', price: 1043.77, pct: 0 },
  ],
  watches: [],
  items: [],
}

const NAMES = [
  ['600519', '贵州茅台', '食品饮料'],
  ['300750', '宁德时代', '电力设备'],
  ['002594', '比亚迪', '汽车'],
  ['601318', '中国平安', '非银金融'],
  ['000858', '五粮液', '食品饮料'],
  ['600036', '招商银行', '银行'],
  ['002415', '海康威视', '电子'],
  ['300059', '东方财富', '非银金融'],
  ['601899', '紫金矿业', '有色金属'],
  ['600276', '恒瑞医药', '医药生物'],
  ['000651', '格力电器', '家用电器'],
  ['601012', '隆基绿能', '电力设备'],
  ['688111', '金山办公', '计算机'],
  ['002230', '科大讯飞', '计算机'],
  ['600030', '中信证券', '非银金融'],
  ['601166', '兴业银行', '银行'],
  ['000333', '美的集团', '家用电器'],
  ['300124', '汇川技术', '电力设备'],
]

const boardItems = NAMES.map(([code, name, industry], i) => ({
  code,
  name,
  industry,
  price: 20 + i * 7.31,
  pct: 6.4 - i * 0.74,
  local_pct: 6.1 - i * 0.7,
  local_close: 19.6 + i * 7.2,
  turnover: 0.128 - i * 0.004,
  amount: 3.6e9 - i * 1.1e8,
  low: 19 + i * 7,
  high: 21.5 + i * 7.4,
  status: 'normal',
  instrument_type: 'STOCK',
}))

const strategies = [
  { slug: 'qianlong-close-v3', name: '潜龙出海（V3）' },
  { slug: 'sanyuan-tail-v1', name: '三源尾盘共振' },
  { slug: 'yangshi-tail-v1', name: '杨氏尾盘选股' },
]

const histories = strategies.map((s, si) => {
  const dates = ['2026-08-27', '2026-08-26', '2026-08-25', '2026-08-24', '2026-08-21']
  const by_date = {}
  for (const d of dates) {
    by_date[d] = NAMES.slice(si * 3, si * 3 + 5).map(([code, name], i) => ({
      code,
      name,
      score: 92 - i * 3 - si,
      reason: '量价共振',
      decision: '精选',
    }))
  }
  return { strategy: s.slug, total: 40, dates, by_date }
})

const outcomes = NAMES.slice(0, 16).map(([code, name], i) => ({
  code,
  name,
  base_date: ['2026-08-26', '2026-08-25', '2026-08-24', '2026-08-21'][i % 4],
  strategy_slug: strategies[i % 3].slug,
  rule_version: strategies[i % 3].slug,
  base_close: 30 + i * 5.5,
  swing_pct: 4.8 - i * 0.3,
  score: 90 - i,
  returns: { t1: 1.9 - i * 0.35, t3: 3.4 - i * 0.5 },
}))

const brief = {
  trade_date: TODAY,
  available: true,
  fetched_at: `${TODAY}T10:40:00`,
  emotion: {
    limit_up_count: 41,
    limit_down_count: 6,
    promotion_rate: 42,
    broken_rate: 18,
    temperature: 61,
    advancers: 2841,
    decliners: 1932,
    promotion_rate_basis: '1进2',
  },
  themes: [
    { code: 'BK1', name: '固态电池', strength: 90, pct_chg: 3.2, main_net_amount_text: '12.4亿' },
    { code: 'BK2', name: '算力租赁', strength: 80, pct_chg: 2.1, main_net_amount_text: '8.1亿' },
    { code: 'BK3', name: '低空经济', strength: 70, pct_chg: -1.4, main_net_amount_text: '-3.2亿' },
  ],
  ladder: { count: 41, height: 5 },
  tools: {},
  source: 'intel_snapshots',
  note: '',
}

const jobs = [
  { id: 'j1', kind: 'screen', job_name: '潜龙收盘选股', enabled: true, schedule: '15:05' },
  { id: 'j2', kind: 'sync', job_name: '日线同步', enabled: true, schedule: '16:00' },
]

const alerts = [
  { code: '600519', name: '贵州茅台', plan_id: 'p1', title: '止损', status: 'stop_hit', note: '' },
  { code: '000858', name: '五粮液', plan_id: 'p2', title: '目标', status: 'target_hit', note: '' },
  { code: '002594', name: '比亚迪', plan_id: 'p3', title: '接近止损', status: 'near_stop', note: '' },
]

export function payloadFor(url) {
  if (url.includes('/auth/session')) {
    return { authenticated: true, username: user.username, user }
  }
  if (url.includes('/auth/me')) return { user, unread: 0 }
  if (url.includes('/auth/notifications')) return { items: [], unread: 0 }
  if (url.includes('/market/session')) return session
  if (url.includes('/market/live-tape')) return tape
  if (url.includes('/market/board')) {
    return { items: boardItems, total: boardItems.length, as_of: NOW, live_error: '' }
  }
  if (url.includes('/strategies')) return strategies
  if (url.includes('/screen/history/batch')) return { histories }
  if (url.includes('/review/candidates')) return { outcomes, summary: {} }
  if (url.includes('/intel/brief')) return brief
  if (url.includes('/alerts/today')) return alerts
  if (url.includes('/jobs/schedule')) {
    return { jobs: [{ id: 'j1', next_run_at: `${TODAY}T15:05:00` }] }
  }
  if (url.includes('/jobs/runs')) return []
  if (url.includes('/jobs')) return jobs
  if (url.includes('/notifications')) return []
  return {}
}

/**
 * 降级态：行情/触价 500，选股历史空，作业有失败运行。
 * 用来自查「一行异常条 + 一行空态 + 作业点展开」是否还守住版面。
 */
export function routeFor(url, mode = 'normal') {
  if (mode !== 'degraded') return { json: payloadFor(url) }
  if (url.includes('/market/live-tape')) {
    return { status: 500, json: { detail: 'akshare 东财接口 502，实时行情不可用' } }
  }
  if (url.includes('/alerts/today')) {
    return { status: 500, json: { detail: '预案库锁竞争，触价提醒暂不可用' } }
  }
  if (url.includes('/screen/history/batch')) return { json: { histories: [] } }
  if (url.includes('/review/candidates')) return { json: { outcomes: [], summary: {} } }
  if (url.includes('/intel/brief')) {
    return { status: 503, json: { detail: '情报缓存未命中' } }
  }
  if (url.includes('/jobs/runs')) {
    return {
      json: [
        {
          id: 'r1',
          job_id: 'j1',
          job_name: '潜龙收盘选股',
          kind: 'screen',
          status: 'failed',
          started_at: `${TODAY}T09:05:00`,
          error_text: 'TdxReader: 数据目录不可读（E:/new_tdx/vipdoc 不存在）',
        },
      ],
    }
  }
  return { json: payloadFor(url) }
}
