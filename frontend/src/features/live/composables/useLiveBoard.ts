import { onActivated, onDeactivated, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import {
  getRecentSignals,
  streamQuotes,
  streamSignals,
  type QuoteFrame,
  type QuoteRow,
  type SignalItem,
  type StreamStatus,
} from '@/shared/api/marketStream'
import type { BoardRow } from '@/shared/types/quant'
import {
  getLiveTape,
  getMarketBoard,
  getMarketDistribution,
  type MarketDistribution,
} from '@/shared/api/quant_market'

/**
 * 信号保留策略——用户原话：
 *   「只看近期出现的信号，超过 7 天自动销毁，只看最新的 80 条。」
 *
 * 服务端 /api/market/signals/recent 已按同样口径裁过，这里再兜一层：推流会
 * 一直往上追加，挂机过夜后那 80 条里就会混进隔夜的老信号。
 */
export const SIGNAL_MAX_AGE_DAYS = 7
export const SIGNAL_MAX_ITEMS = 80
const SIGNAL_MAX_AGE_MS = SIGNAL_MAX_AGE_DAYS * 24 * 60 * 60 * 1000

export type ConnectionStatus = 'connecting' | 'connected' | 'reconnecting' | 'offline'

/** 大屏同时挂两条 SSE：行情（preset=all）与信号（preset=signals）。 */
type FeedOrigin = 'quotes' | 'signals'
export function useLiveBoard() {
  const status = ref<ConnectionStatus>('connecting')
  const lastAsOf = ref<string>('')
  const source = ref<string>('stream')
  const sessionPhase = ref<string>('closed')
  const isLive = ref<boolean>(false)
  const distribution = ref<MarketDistribution | null>(null)

  // 核心行情数据
  const quotesMap = shallowRef<Map<string, QuoteRow>>(new Map())
  const indexRows = shallowRef<QuoteRow[]>([])
  /**
   * 指数分时点列（新增，向后兼容）：code → 最近 N 个点位。
   *
   * 指数带右侧那枚 sparkline 需要一条**真实**走势。旧的 IndexMiniChart 在没有
   * 历史时用 sin() 造过一条假曲线——那是在骗人。这里只累计推流真实到达的点，
   * 没有点就让 sparkline 画一条平线。上限 240 点（3s 一帧约 12 分钟窗口）。
   */
  const indexTrails = shallowRef<Map<string, number[]>>(new Map())
  const MAX_TRAIL_POINTS = 240
  const gainersRows = shallowRef<QuoteRow[]>([])
  const losersRows = shallowRef<QuoteRow[]>([])
  const turnoverRows = shallowRef<QuoteRow[]>([])
  const amountRows = shallowRef<QuoteRow[]>([])

  // 信号流：7 天内 + 最新 80 条（见文件顶部两个常量）
  const signals = ref<SignalItem[]>([])
  const newSignalIds = ref<Set<string>>(new Set())
  /**
   * 链路已建立但**数据源没喂上来**时的真相：`dataStale`。
   *
   * 病灶：旧版把 status 判成 'connected' 的唯一时机是「收到第一帧」。
   * 上游东财的全市场截面一挂（生产日志里 `实时推流 feed all 取数失败` 每分钟数条），
   * 后端仍会正常保持 SSE 并每 15s 发心跳——链路完好，只是没数据。此时界面却显示
   * 「连接中 / 重连中 / 连接中断」，用户原话「动不动就是连接中断」。
   *
   * 现在：`status` 只描述**链路**（onOpen 即 connected），数据新鲜度单独由
   * `dataStale` 表达。两件事分开报，才不会拿链路去背数据源的锅。
   */
  const dataStale = ref<boolean>(false)
  /**
   * 采集器最近一次失败的原因（来自 `hello` / `heartbeat`）。空串 = 数据源正常。
   *
   * 大屏必须能回答「为什么不动」：上游整表取数挂掉时，链路、心跳、HTTP 状态
   * 全都正常，只有这一句能把「数据源挂了」和「现在没行情」区分开。
   */
  const sourceError = ref<string>('')
  /** 两条流各自的上游故障；对外汇总成一个 sourceError，但记账必须分开 */
  const feedErrors: Record<FeedOrigin, string> = { quotes: '', signals: '' }
  /** 最近一帧行情距今多久（毫秒）。-1 = 这条流还没喂过任何数据。 */
  const staleMs = ref<number>(-1)
  let lastFrameAt = 0
  let staleTimer: number | null = null
  /**
   * start/stop 的重入闸。
   *
   * **首次挂载在 KeepAlive 里时,onMounted 与 onActivated 会双双触发**,
   * 不挡就会建两条重复的行情流+两条信号流(单测 useLiveBoard.lifecycle 钉住了这点)。
   * 连接翻倍本身就是「动不动就中断」的成因之一,别自己制造。
   */
  let running = false
  /** 本次 start() 的时刻：用来判「链路开着但一帧都没来」有多久了 */
  let startedAt = 0
  /**
   * 判定「数据过期」的阈值。后端心跳 15s 一发，采集失败时走指数退避、上限 30s
   * (live_hub.MAX_BACKOFF_SECONDS)，所以 45s 是「连着三轮都没喂上来」，不是抖一下就报。
   */
  const STALE_AFTER_MS = 45_000
  /** 首屏信号历史只回填一次；重连不重复打 */
  let historyLoaded = false
  let abortController: AbortController | null = null
  let retryTimer: number | null = null
  let retryDelayMs = 1000
  let isPageVisible = true
  let generation = 0

  /**
   * 合并信号：先按 triggeredAt 丢掉超 7 天的，再按时间倒序取最新 80 条。
   *
   * `markNew=false` 给首屏历史回填用——那些是「早先发生过的」，不是「刚到的」，
   * 整屏闪一遍高亮动画只会让人以为盘中突然爆出 80 个信号。
   */
  function addSignals(incoming: SignalItem[], markNew = true) {
    if (!incoming.length) return

    // 去重：同 id 以新到的为准
    const map = new Map<string, SignalItem>()
    for (const item of incoming) {
      map.set(item.id, item)
    }
    for (const item of signals.value) {
      if (!map.has(item.id)) map.set(item.id, item)
    }

    const cutoff = Date.now() - SIGNAL_MAX_AGE_MS
    const fresh = Array.from(map.values()).filter((item) => {
      const ts = Date.parse(item.triggeredAt)
      // 时间戳缺失/解析不出的留着：宁可多留一条真信号，也别按「看不懂时间」清掉
      if (!Number.isFinite(ts)) return true
      return ts >= cutoff
    })
    // Date.parse 解析不出来是 NaN（falsy）→ 归 0，排到列表最后
    fresh.sort((a, b) => (Date.parse(b.triggeredAt) || 0) - (Date.parse(a.triggeredAt) || 0))
    const kept = fresh.slice(0, SIGNAL_MAX_ITEMS)
    signals.value = kept

    if (!markNew) return
    // 标记新信号以触发动画高亮（只标真的留在列表里的）
    const keptIds = new Set(kept.map((item) => item.id))
    for (const item of incoming) {
      if (!keptIds.has(item.id)) continue
      const id = item.id
      newSignalIds.value.add(id)
      setTimeout(() => {
        newSignalIds.value.delete(id)
      }, 1400)
    }
  }

  /** 把本帧指数点位追加进分时点列；重复点位不入列，免得平盘时白撑数组 */
  function pushIndexTrails(rows: QuoteRow[]) {
    if (!rows.length) return
    const next = new Map(indexTrails.value)
    let touched = false
    for (const row of rows) {
      if (!Number.isFinite(row.price) || row.price <= 0) continue
      const prev = next.get(row.code) ?? []
      if (prev.length && prev[prev.length - 1] === row.price) continue
      const list = [...prev, row.price]
      next.set(row.code, list.slice(Math.max(0, list.length - MAX_TRAIL_POINTS)))
      touched = true
    }
    if (touched) indexTrails.value = next
  }

  /** 链路活着（onOpen 或任何一帧/一条信号到达）。只动链路状态，不碰数据新鲜度。 */
  function markLinkUp(): void {
    status.value = 'connected'
  }

  /**
   * `hello` / `heartbeat`：**没有行情帧时，会话相位与数据源现状的唯一来源**。
   *
   * 旧版把 phase / live 只从行情帧里取，而后端那时压根没发这两个键（契约缺口），
   * 于是全天兜底成 'closed'：连续竞价里顶栏挂着「已收盘·展示最近快照」，
   * 看门狗因为 isLive=false 永不触发，一屏冻住的数字没有一处交代原因。
   */
  function applyStatus(next: StreamStatus, origin: FeedOrigin): void {
    markLinkUp()
    sessionPhase.value = next.session.phase
    isLive.value = next.session.live
    // **按流分开记**：两条流各有各的上游。混在一个字段里时，信号流那句
    // 「我这边没事」会立刻擦掉行情流刚报的「东财整表挂了」，界面转眼又说
    // 「实时推流中」——比不报还坏。
    feedErrors[origin] = next.sourceError
    sourceError.value = feedErrors.quotes || feedErrors.signals
    if (origin === 'quotes') {
      if (next.staleMs >= 0) staleMs.value = next.staleMs
      // 从没喂过数据也是一种「过期」：只要开着盘就得说出来
      if (next.staleMs < 0 && next.session.live) dataStale.value = true
    }
    if (sourceError.value) dataStale.value = true
  }

  function handleQuotesFrame(frame: QuoteFrame) {
    markLinkUp()
    lastFrameAt = Date.now()
    dataStale.value = false
    staleMs.value = 0
    feedErrors.quotes = ''
    sourceError.value = feedErrors.signals
    lastAsOf.value = frame.asOf
    source.value = frame.source
    sessionPhase.value = frame.session.phase
    isLive.value = frame.session.live

    // 按类别拆分行
    const newMap = new Map(quotesMap.value)
    for (const row of frame.rows) {
      newMap.set(row.code, row)
    }
    quotesMap.value = newMap

    // 如果返回的行具备指数或全市场特征，分别派发
    const indices: QuoteRow[] = []
    const stocks: QuoteRow[] = []
    for (const row of frame.rows) {
      if (
        row.code.startsWith('sh000') ||
        row.code.startsWith('sz399') ||
        row.code === '000001' ||
        row.code === '399001' ||
        row.code === '399006' ||
        row.code === '000300' ||
        row.code === '000688'
      ) {
        indices.push(row)
      } else {
        stocks.push(row)
      }
    }

    if (indices.length > 0) {
      indexRows.value = indices
      pushIndexTrails(indices)
    }

    if (stocks.length > 0) {
      // 涨幅榜
      gainersRows.value = [...stocks].sort((a, b) => b.pct - a.pct).slice(0, 10)
      // 跌幅榜
      losersRows.value = [...stocks].sort((a, b) => a.pct - b.pct).slice(0, 10)
      // 换手榜
      turnoverRows.value = [...stocks].sort((a, b) => b.turnover - a.turnover).slice(0, 10)
      // 成交额榜
      amountRows.value = [...stocks].sort((a, b) => b.amount - a.amount).slice(0, 10)
    }
  }

  async function loadInitialSnapshot() {
    // 首屏/收盘先拉一次本地与最近快照：指数与四个榜单都是**真实**落库数据。
    // 注意这里只填行情，不碰信号——信号没有就是没有，见 loadRecentSignals。
    try {
      const [tape, boardSample, boardGainers, boardLosers, boardTurnover, boardAmount, dist] =
        await Promise.allSettled([
          getLiveTape(true),
          getMarketBoard({ page_size: 100, instrument_type: 'STOCK', status: 'normal' }),
          getMarketBoard({
            sort: 'pct_desc',
            page_size: 10,
            instrument_type: 'STOCK',
            status: 'normal',
          }),
          getMarketBoard({
            sort: 'pct_asc',
            page_size: 10,
            instrument_type: 'STOCK',
            status: 'normal',
          }),
          getMarketBoard({
            sort: 'turnover_desc',
            page_size: 10,
            instrument_type: 'STOCK',
            status: 'normal',
          }),
          getMarketBoard({
            sort: 'amount_desc',
            page_size: 10,
            instrument_type: 'STOCK',
            status: 'normal',
          }),
          getMarketDistribution(),
        ])

      if (dist.status === 'fulfilled' && dist.value?.total_count) {
        distribution.value = dist.value
      }

      const map = new Map(quotesMap.value)
      if (tape.status === 'fulfilled' && tape.value?.indices) {
        const idxList: QuoteRow[] = []
        for (const item of tape.value.indices) {
          const p = Number(item.price ?? 0)
          const pct = Number(item.pct ?? 0)
          const prev = pct !== 0 && p > 0 ? p / (1 + pct / 100) : p
          const row: QuoteRow = {
            code: item.code || '',
            name: item.name || item.label || '',
            price: p,
            prevClose: prev,
            change: Number(item.change ?? 0),
            pct,
            volume: 0,
            amount: 0,
            turnover: 0,
            amplitude: 0,
            speed: 0,
            high: Number(item.price ?? 0),
            low: Number(item.price ?? 0),
            open: Number(item.price ?? 0),
            staleMs: 0,
          }
          idxList.push(row)
          map.set(row.code, row)
        }
        if (indexRows.value.length === 0 && idxList.length > 0) {
          indexRows.value = idxList
        }
        // 快照只给得出一个点：够 sparkline 判定「有没有数据」，画不出走势也不编
        pushIndexTrails(idxList)
        if (!lastAsOf.value && tape.value.as_of) {
          lastAsOf.value = tape.value.as_of
        }
      }

      const toRows = (items: BoardRow[]): QuoteRow[] => {
        return items.map((b) => {
          const p = Number(b.price ?? b.local_close ?? 0)
          const pct = Number(b.pct ?? b.local_pct ?? 0)
          const prev = Number(b.prev_close ?? (pct !== 0 && p > 0 ? p / (1 + pct / 100) : p))
          const r: QuoteRow = {
            code: String(b.code || ''),
            name: String(b.name || ''),
            price: p,
            prevClose: prev,
            change: Number(b.change ?? b.local_change ?? 0),
            pct,
            volume: Number(b.volume ?? 0),
            amount: Number(b.amount ?? 0),
            turnover: Number(b.turnover ? Number(b.turnover) * 100 : 0),
            amplitude: 0,
            speed: 0,
            high: Number(b.high ?? p),
            low: Number(b.low ?? p),
            open: Number(b.open ?? p),
            staleMs: 0,
          }
          map.set(r.code, r)
          return r
        })
      }
      if (boardSample.status === 'fulfilled' && boardSample.value?.items?.length) {
        toRows(boardSample.value.items)
      }
      if (boardGainers.status === 'fulfilled' && gainersRows.value.length === 0) {
        gainersRows.value = toRows(boardGainers.value.items || [])
      }
      if (boardLosers.status === 'fulfilled' && losersRows.value.length === 0) {
        losersRows.value = toRows(boardLosers.value.items || [])
      }
      if (boardTurnover.status === 'fulfilled' && turnoverRows.value.length === 0) {
        turnoverRows.value = toRows(boardTurnover.value.items || [])
      }
      if (boardAmount.status === 'fulfilled' && amountRows.value.length === 0) {
        amountRows.value = toRows(boardAmount.value.items || [])
      }
      quotesMap.value = map
    } catch {
      /* 容错兜底 */
    }
  }

  /**
   * 首屏信号历史：真规则引擎落库的最近信号（服务端已裁到 7 天内、≤80 条、倒序）。
   *
   * 接口没就绪 / 404 / 报错，结果都只是「没有历史」——直接空态。这里以前是拿
   * 涨幅榜、成交额榜、换手榜换个标签造信号顶上：那不是策略，是把榜单数据在
   * 旁边又说了一遍。没信号就是没信号。
   */
  async function loadRecentSignals() {
    try {
      const recent = await getRecentSignals(SIGNAL_MAX_ITEMS)
      addSignals(recent.items, false)
      if (!lastAsOf.value && recent.asOf) lastAsOf.value = recent.asOf
    } catch {
      /* 拉不到历史 = 没有历史 */
    }
  }

  async function connect() {
    if (!isPageVisible) return
    // stopStream() 已 abort 上一轮控制器并清掉重试定时器，所以重连不会堆连接
    stopStream()

    void loadInitialSnapshot()
    // 历史只在首次建链时回填一次；重连不该重复打这一枪
    if (!historyLoaded) {
      historyLoaded = true
      void loadRecentSignals()
    }

    const currentGen = ++generation
    abortController = new AbortController()
    const signal = abortController.signal
    status.value = status.value === 'offline' ? 'reconnecting' : 'connecting'

    // 并行启动行情与信号推流
    const quotesPromise = streamQuotes({
      preset: 'all',
      signal,
      onOpen: () => {
        if (currentGen !== generation) return
        markLinkUp()
      },
      onStatus: (next) => {
        if (currentGen !== generation) return
        applyStatus(next, 'quotes')
      },
      onFrame: (frame) => {
        if (currentGen !== generation) return
        retryDelayMs = 1000
        handleQuotesFrame(frame)
      },
      onError: () => {
        if (currentGen !== generation) return
        scheduleReconnect()
      },
    })

    const signalsPromise = streamSignals({
      preset: 'signals',
      signal,
      onOpen: () => {
        if (currentGen !== generation) return
        markLinkUp()
      },
      onStatus: (next) => {
        if (currentGen !== generation) return
        applyStatus(next, 'signals')
      },
      onSignals: (items) => {
        if (currentGen !== generation) return
        retryDelayMs = 1000
        markLinkUp()
        addSignals(items)
      },
      onError: () => {
        if (currentGen !== generation) return
        scheduleReconnect()
      },
    })

    await Promise.allSettled([quotesPromise, signalsPromise])
  }
  function scheduleReconnect() {
    if (!isPageVisible) return
    status.value = 'reconnecting'
    if (retryTimer !== null) {
      clearTimeout(retryTimer)
      retryTimer = null
    }

    retryTimer = window.setTimeout(() => {
      retryDelayMs = Math.min(retryDelayMs * 2, 30000)
      void connect()
    }, retryDelayMs)
  }

  function stopStream() {
    if (abortController) {
      abortController.abort()
      abortController = null
    }
    if (retryTimer !== null) {
      clearTimeout(retryTimer)
      retryTimer = null
    }
  }

  function handleVisibilityChange() {
    if (typeof document === 'undefined') return
    if (document.hidden) {
      isPageVisible = false
      stopStream()
      status.value = 'offline'
    } else {
      isPageVisible = true
      retryDelayMs = 1000
      void connect()
    }
  }

  /*
   * 生命周期必须走 activated / deactivated。
   *
   * PageHost.vue 用 <KeepAlive :max="12"> 包住所有非档案路由，**离开大屏不会触发
   * onUnmounted**。旧版把 stopStream 挂在 onUnmounted 上，于是点开一次大屏之后，
   * 两条 SSE 流在后台一直挂着；再进来又不会重连（onMounted 也不再触发），
   * 界面停在上一次的残留状态。这既是「动不动就中断」的一半成因，也白占服务端订阅。
   *
   * mounted/unmounted 仍保留：非 KeepAlive 场景（单测直接 mount）靠它们成对。
   * start/stop 各自幂等，两套钩子叠加触发也不会重复建链。
   */
  function start(): void {
    if (running) return
    running = true
    startedAt = Date.now()
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', handleVisibilityChange)
    }
    isPageVisible = typeof document === 'undefined' || !document.hidden
    // 数据新鲜度看门狗：**只在交易时段**判过期——收盘后没有新帧是正常的，
    // 那种情况下顶栏胶囊已经在说「已收盘」，再叠一个「数据源异常」就是造谣。
    // 建在可见性判断**之前**：页面一开始就处于后台时也要有看门狗，
    // 否则切回前台恢复推流后这块永远不判新鲜度。
    if (staleTimer === null && typeof window !== 'undefined') {
      staleTimer = window.setInterval(() => {
        if (!isLive.value || status.value !== 'connected') {
          dataStale.value = false
          staleMs.value = lastFrameAt > 0 ? Date.now() - lastFrameAt : -1
          return
        }
        // 「一帧都没收到」同样算过期。旧版要求 lastFrameAt > 0，于是上游从一开始就
        // 挂着时看门狗永不触发——大屏整天显示「已连接」，数字停在 REST 首屏快照上。
        const since = lastFrameAt > 0 ? Date.now() - lastFrameAt : Date.now() - startedAt
        staleMs.value = lastFrameAt > 0 ? Date.now() - lastFrameAt : -1
        dataStale.value = since > STALE_AFTER_MS || Boolean(sourceError.value)
      }, 5_000)
    }
    if (!isPageVisible) return
    void connect()
  }

  function stop(): void {
    if (!running) return
    running = false
    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
    stopStream()
    if (staleTimer !== null) {
      clearInterval(staleTimer)
      staleTimer = null
    }
  }

  onMounted(start)
  onActivated(start)
  onDeactivated(stop)
  onUnmounted(stop)

  return {
    status,
    /** 链路好但上游没喂数据(交易时段专属);与 status 分开报 */
    dataStale,
    /** 采集器最近一次失败原因；空串=数据源正常。界面据此说「数据源取数失败」 */
    sourceError,
    /** 最近一帧行情距今毫秒；-1=这条流还没喂过数据 */
    staleMs,
    lastAsOf,
    source,
    sessionPhase,
    isLive,
    distribution,
    quotesMap,
    indexRows,
    /** 新增字段：指数分时点列，纯累加，老调用方忽略即可 */
    indexTrails,
    gainersRows,
    losersRows,
    turnoverRows,
    amountRows,
    signals,
    newSignalIds,
    connect,
    stopStream,
  }
}
