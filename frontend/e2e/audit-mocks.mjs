/**
 * 验收自查用的 mock 补丁层。
 *
 * `pulse-mocks.mjs` 是给盘面首页写的，未命中的 `/api/**` 一律回 `{}`。而
 * /winrate、/ops、/quant、/archive 这些页面的字段契约有的是**数组**、有的是
 * **带固定子对象的结构体**，收到 `{}` 就抛 `xxx.map is not a function` /
 * `Cannot read properties of undefined`，页面顶上冒出一条 el-alert。
 *
 * **那是 mock 形状不对，不是产品坏了。** 但要用浏览器核验渲染与观感，就得先让
 * 页面真的画出来——否则「没报错」只是因为组件根本没挂载。所以这一层的职责是：
 * 严格按 `src/shared/types/**` 的契约补形状，一个字段都不能少。
 *
 * 只补 mock，不改任何产品代码。
 */
import { payloadFor } from './pulse-mocks.mjs'

/*
 * 定时任务。pulse-mocks 的 jobs 夹具写的是 `job_name`（那是 JobRun 的字段），
 * 而 `Job` 契约是 `name` —— `jobOwnership.ts` 读 `job.name.startsWith()` 直接炸。
 * 这里按 shared/types/quant-ops.ts 的 `Job` 重给一份完整的。
 */
const JOBS = [
  {
    id: 'j1',
    name: 'screen:sanyuan-tail-v1',
    kind: 'screen',
  cron: '5 15 * * 1-5',
    config: { strategy: 'sanyuan-tail-v1' },
    enabled: true,
    last_run_at: '2026-08-28 15:05:12',
 last_status: 'ok',
    created_at: '2026-01-01 00:00:00',
    updated_at: '2026-08-28 15:05:12',
  },
  {
    id: 'j2',
    name: 'sync:daily',
    kind: 'sync',
    cron: '0 16 * * 1-5',
    config: {},
  enabled: true,
    last_run_at: '2026-08-28 16:00:03',
    last_status: 'ok',
    created_at: '2026-01-01 00:00:00',
    updated_at: '2026-08-28 16:00:03',
  },
]

/** 候选验证。`summary.missed_winners` 是数组，缺了 ReviewCenterView 模板就崩 */
const REVIEW_CANDIDATES = {
  outcomes: [],
  summary: {
    total: 0,
    evaluated: 0,
    by_decision: {},
    selected: {},
    rejected: {},
    missed_winners: [],
  },
}

/** QuoteSeries：字段叫 `bars` 不是 `rows`；KlineChart 读 `props.bars.length` */
const QUOTE_SERIES = {
  code: '600519',
  name: '贵州茅台',
  market: 'SH',
  board: 'main',
  board_label: '主板',
  industry: '白酒',
  adjust: 'qfq',
  rows: 0,
  total_rows: 0,
  bars: [],
}

/*
 * 需求 8 的取证数据：故意喂**英文 slug**（用户截图里那三个），页面必须渲染成中文。
 * 回空数组等于什么都没验到——表格不渲染，断言自然「通过」。
 */
const WINRATE_SUMMARY = [
  {
    strategy_tag: 'sanyuan-tail-v1',
    source: 'candidates',
    total: 14,
    wins: 8,
    win_rate: 57.14,
    avg_return: 1.23,
    observing: 3,
    sample_all: 17,
    primary_horizon: 5,
    last_reviewed: '2026-08-28',
    horizons: {
      t1: { horizon: 1, n: 14, avg: 0.6, win_rate: 66.7, best: 7.2, worst: -4.1 },
      t3: { horizon: 3, n: 14, avg: 1.1, win_rate: 50, best: 9.4, worst: -6.3 },
      t5: { horizon: 5, n: 14, avg: 1.23, win_rate: 57.14, best: 12.6, worst: -8.2 },
      t20: { horizon: 20, n: 11, avg: 3.4, win_rate: 63.6, best: 24.1, worst: -11.5 },
    },
    best_horizon: { horizon: 20, n: 11, avg: 3.4, win_rate: 63.6 },
    best_sample: {
      code: '688697',
      name: '纽威数控',
      base_date: '2026-08-25',
      base_close: 31.2,
      return_pct: 12.6,
      max_favorable_pct: 15.1,
      horizon: 5,
    },
    worst_sample: {
      code: '300750',
      name: '宁德时代',
      base_date: '2026-08-19',
      base_close: 210.4,
      return_pct: -8.2,
      max_favorable_pct: 1.2,
      horizon: 5,
    },
  },
  {
    strategy_tag: 'qianlong-close-v3',
    source: 'candidates',
    total: 9,
    wins: 5,
    win_rate: 55.5,
    avg_return: -0.4,
    observing: 2,
    sample_all: 11,
    primary_horizon: 5,
    last_reviewed: '2026-08-28',
    horizons: {
      t1: { horizon: 1, n: 9, avg: 0.2, win_rate: 60, best: 5.5, worst: -3.9 },
      t3: { horizon: 3, n: 9, avg: 0.9, win_rate: 100, best: 8.1, worst: 0.4 },
      t5: { horizon: 5, n: 9, avg: -0.4, win_rate: 55.5, best: 6.7, worst: -7.7 },
    },
    best_horizon: { horizon: 3, n: 9, avg: 0.9, win_rate: 100 },
    best_sample: {
      code: '002415',
      name: '海康威视',
      base_date: '2026-08-21',
      base_close: 28.6,
      return_pct: 6.7,
      max_favorable_pct: 8.3,
      horizon: 5,
    },
    worst_sample: {
      code: '600519',
      name: '贵州茅台',
      base_date: '2026-08-14',
      base_close: 1420.0,
      return_pct: -7.7,
      max_favorable_pct: 0.6,
      horizon: 5,
    },
  },
  {
    strategy_tag: 'yangshi-tail-v1',
    source: 'reviews',
    total: 6,
    wins: 2,
    win_rate: 33.3,
    avg_return: 0.8,
    last_reviewed: '2026-08-27',
    horizons: {},
    best_horizon: null,
    best_sample: null,
    worst_sample: null,
  },
]

/** 样本明细：胜率的分母长什么样。回数组会让面板读 `.settled` 拿到 undefined。 */
const WINRATE_SAMPLES = {
  strategy_tag: 'sanyuan-tail-v1',
  primary_horizon: 5,
  settled: 14,
  observing: 3,
  wins: 8,
  win_rate: 57.14,
  avg_return: 1.23,
  sample_confidence: 'medium',
  truncated: false,
  samples: [
    {
      candidate_id: 'CR-1',
      code: '688697',
      name: '纽威数控',
      base_date: '2026-08-25',
      base_close: 31.2,
      returns: { t1: 2.1, t3: 5.4, t5: 12.6, t10: 14.2, t20: 24.1, t60: null },
      alpha: { t5: 11.4 },
      max_favorable_pct: 15.1,
      swing_pct: 18.2,
      note: '',
      tier: 'core',
      win: true,
      primary_return: 12.6,
    },
    {
      candidate_id: 'CR-2',
      code: '300750',
      name: '宁德时代',
      base_date: '2026-08-19',
      base_close: 210.4,
      returns: { t1: -1.2, t3: -4.6, t5: -8.2, t10: -6.1, t20: 2.3, t60: null },
      alpha: { t5: -9.1 },
      max_favorable_pct: 1.2,
      swing_pct: 9.9,
      note: '',
      tier: 'core',
      win: false,
      primary_return: -8.2,
    },
    {
      candidate_id: 'CR-3',
      code: '002415',
      name: '海康威视',
      base_date: '2026-09-02',
      base_close: 28.6,
      returns: { t1: 0.9, t3: null, t5: null, t10: null, t20: null, t60: null },
      alpha: { t5: null },
      max_favorable_pct: 1.4,
      swing_pct: 2.2,
      note: '短线窗口未满（待 T+3/T+5）',
      tier: 'core',
      win: null,
      primary_return: null,
    },
  ],
}

const WINRATE_TREND = ['sanyuan-tail-v1', 'qianlong-close-v3', 'yangshi-tail-v1'].flatMap((tag) =>
  ['2026-06', '2026-07', '2026-08'].map((period) => ({
  period,
    strategy_tag: tag,
    total: 5,
    wins: 3,
    win_rate: 60,
    avg_return: 1.1,
    source: 'candidates',
  })),
)

/*
 * 明确要「结构体」的端点。必须在数组规则**之前**判定：`/mcp/quota` 会被 `/mcp`
 * 前缀误判成数组，页面读 `.remaining.total` 就炸。键用 endsWith 匹配，
 * 带路径参数的（`/market/quotes/{code}`）走下面的 includes 分支。
 */
const OBJECT_ENDPOINTS = {
  // LanesCatalog（shared/types/quant-ops.ts）
  '/ops/lanes': {
    lanes: [],
    providers: [],
    policies: [],
    summary: { total: 0, healthy: 0, degraded: 0 },
  },
  // MarketCoverage
  '/market/coverage': {
    rows: 0,
    codes: 0,
    first_date: '',
    last_date: '',
  failed_codes: 0,
    db_path: '',
db_bytes: 0,
  },
  // ScreenSkillCatalog：五个数组字段少一个都会崩
  '/screen-skills/catalog': {
    runtimes: [],
    dialects: [],
    fields: [],
    functions: [],
    snippets: [],
  },
  // UniverseStats
  '/universe/stats': {
    total: 0,
    by_board: {},
    st_count: 0,
    selectable_default: 0,
    bse_blocked: false,
    as_of: '',
  },
  // JobQuota —— 会被 pulse-mocks 的 /jobs 前缀抢成数组，必须显式覆盖
  '/jobs/quota': { used: 0, limit: 20, unlimited: false, managed: 0 },
  // 纸面舱（QuantView 的「纸面量化」Tab）
  // 纸面舱走下面的 PAPER_CABIN（按路径前缀匹配，不写死 slug）
  '/mcp/quota': {
    trade_date: '2026-08-27',
    limits: { daily_total: 500, structured: 300, skill: 200, per_minute: 30 },
    used: { structured: 0, skill: 0, total: 0 },
    remaining: { structured: 300, skill: 200, total: 500 },
  },
'/mcp/wudao': { available: false, endpoint: '', tools: [], servers: [] },
  '/mcp/wudao/settings': { enabled: false, endpoint: '', token: '' },
  '/ops/settings/notify': { enabled: false, channels: [] },
  '/ops/settings/wecom': { enabled: false, webhook: '', mentions: [] },
  '/ops/data-location': { data_dir: 'E:/loci/data' },
  '/ops/desktop-prefs': { autostart: false, minimize_to_tray: false },
  '/ops/market-sync': { running: false, percent: 0, message: '' },
  '/market/bootstrap': { needed: false, kind: 'none' },
  '/screen/run': { runs: {}, running: false },
}

/** 契约是数组的端点。命中即覆盖 pulse-mocks 的 `{}` 兜底。 */
const ARRAY_ENDPOINTS = [
  // Candidate[] / ReviewRecord[] / UniversePreset[] / StrategyInfo[] / TimelineEvent[]
  '/candidates/list',
  '/reviews',
  '/universe/presets',
  '/screen-skills',
  '/timeline/',
  '/providers',
  '/winrate/summary',
  '/winrate/trend',
  '/ops/alert-rules',
  '/mcp',
  '/research/',
  '/strategies/custom',
  '/skills',
  '/market/akshare/sources',
  '/market/industries',
  '/insights',
  '/health',
  '/llm/',
  '/admin/',
  '/shelf',
]

/*
 * skills / strategies 的**子资源**契约都是对象（SkillJob、SkillStrategyConfig、
 * WatchTuningResponse…）。它们必须在数组兜底之前拦下来，否则 `/skills` 这个
 * 前缀会把 `/skills/{slug}/job` 也变成 `[]`，下游 `hydrate(job)` 拿到数组，
 * 一路 undefined 到 `job.config` 才炸——排查起来像产品 bug，其实是 mock 喂错。
 */
const SUB_RESOURCE = {
  '/job': { slug: 'demo', config: {}, enabled: false, cron: '', next_runs: [] },
  '/strategy-config': { slug: 'demo', config: {}, provider: '', updated_at: '' },
  '/watch-tuning': { slug: 'demo', tuning: {}, applied: false, preview: [] },
  '/watch-preview': { slug: 'demo', rows: [], as_of: '' },
  '/leader-roles': [],
}
/*
 * 纸面舱（PaperQuantPanel / PaperRoleReviewPanel）。
 * 契约见 PaperQuantPanel.vue 的 loadCabin()：顶层要有 cabin / positions / fills /
 * monitor_runs / nextday_plan / unified_pool / style / lessons / memory_graph。
 * 少 `cabin` 就会在 `data.cabin.config` 处直接抛（那行没有可选链）。
 */
const PAPER_CABIN = {
  cabin: { slug: 'demo', config: { paper_quant: {} }, enabled: false, updated_at: '' },
  positions: [],
  fills: [],
  monitor_runs: [],
  nextday_plan: {},
  unified_pool: { counts: { positions: 0, observe: 0 } },
  style: { style_md: '', revision: 0, watch_hints: [] },
  lessons: [],
  memory_graph: { summary: '', nodes: [], edges: [], stats: { nodes: 0, edges: 0, by_kind: {} } },
}
/*
 * 研究目录（ResearchCatalog）。`useResearchProfile.ts` 写的是
 * `catalog.value?.dimensions.length` —— 可选链只护住了 catalog 本身，
 * dimensions 缺了照样抛。六个数组字段都要给。
 */
const RESEARCH_CATALOG = {
  version: 'v1',
  dimensions: [],
  sources: [],
  market_adapters: [],
  quality_values: [],
  budgets: [],
  guardrails: { production_signal: false },
}

/** 研究里的分页列表：组件读 `response.items`，不是裸数组 */
const RESEARCH_PAGED = { items: [], total: 0, page: 1, page_size: 20 }

/** SharePackStatus：PackTab 读 `s.options.filter(...)`，options 必须在 */
const SHARE_PACK_STATUS = {
  version: 'v1.0.0',
  released_at: '2026-08-28',
  summary: '',
  can_pack: false,
  reason: '本机没有编译产物',
  bundle_root: null,
  runtime_bytes: 0,
  options: [],
}

export function auditPayloadFor(url) {
  const path = new URL(url).pathname

  // 需求 8 取证：这两个必须回带英文 slug 的真数据，否则页面空着等于没验
  if (path.endsWith('/winrate/summary')) return WINRATE_SUMMARY
  if (path.endsWith('/winrate/trend')) return WINRATE_TREND
  if (path.endsWith('/winrate/samples')) return WINRATE_SAMPLES

  if (path.endsWith('/jobs')) return JOBS
  if (path.endsWith('/review/candidates')) return REVIEW_CANDIDATES
  if (path.includes('/market/quotes/')) return QUOTE_SERIES
  if (path.includes("/ops/paper-cabins/")) return PAPER_CABIN
  if (path.endsWith("/research/catalog")) return RESEARCH_CATALOG
  if (path.endsWith("/research/backtest-runs")) return RESEARCH_PAGED
  if (path.endsWith("/research/hypotheses")) return RESEARCH_PAGED
  if (path.endsWith("/research/factor-jobs")) return RESEARCH_PAGED
  if (path.endsWith("/research/backtest-jobs")) return RESEARCH_PAGED
  if (path.endsWith("/ops/share-pack/status")) return SHARE_PACK_STATUS
  if (path.includes("/insights/")) return []

  for (const key of Object.keys(SUB_RESOURCE)) {
    if (path.endsWith(key)) return SUB_RESOURCE[key]
  }

  for (const key of Object.keys(OBJECT_ENDPOINTS)) {
    if (path.endsWith(key)) return OBJECT_ENDPOINTS[key]
  }

  const base = payloadFor(url)
  // pulse-mocks 已经给了具体形状就不动它
  const isEmptyObject =
    base && typeof base === 'object' && !Array.isArray(base) && Object.keys(base).length === 0
  if (!isEmptyObject) return base

  /*
   * 数组兜底用**尾部精确匹配**，不能用 includes：`/skills` 会连 `/skills/{slug}/job`
   * 一起吞掉。真正是前缀语义的（`/research/` `/llm/` `/admin/` `/timeline/`）
   * 在表里以 `/` 结尾，单独走 includes。
   */
  const exact = ARRAY_ENDPOINTS.filter((e) => !e.endsWith('/'))
  const prefix = ARRAY_ENDPOINTS.filter((e) => e.endsWith('/'))
  if (exact.some((e) => path.endsWith(e))) return []
  if (prefix.some((e) => path.includes(e))) return []
  return base
}

export function auditRouteFor(url) {
  return { json: auditPayloadFor(url) }
}
