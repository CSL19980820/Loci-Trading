import { quantRequest, query } from '@/shared/api/quant_client'

export type QuoteRow = {
  code: string
  name: string
  price: number
  prevClose: number
  change: number
  pct: number
  volume: number
  amount: number
  turnover: number
  amplitude: number
  speed: number
  high: number
  low: number
  open: number
  staleMs: number
}

export type QuoteFrame = {
  seq: number
  asOf: string
  source: string
  session: { phase: string; live: boolean }
  rows: QuoteRow[]
}

export type SignalItem = {
  id: string
  code: string
  name: string
  strategy: string
  strategyName: string
  title: string
  detail: string
  direction: 'long' | 'watch' | 'exit'
  strength: number
  price: number
  pct: number
  provisional: boolean
  triggeredAt: string
}

type RawQuoteRow = {
  code?: string
  name?: string
  price?: number
  prev_close?: number
  prevClose?: number
  change?: number
  pct?: number
  volume?: number
  amount?: number
  turnover?: number
  amplitude?: number
  speed?: number
  high?: number
  low?: number
  open?: number
  stale_ms?: number
  staleMs?: number
}

type RawQuoteFrame = {
  seq?: number
  as_of?: string
  asOf?: string
  source?: string
  session?: { phase?: string; live?: boolean }
  rows?: RawQuoteRow[]
}

type RawSignalItem = {
  id?: string
  code?: string
  name?: string
  strategy?: string
  strategy_name?: string
  strategyName?: string
  title?: string
  detail?: string
  direction?: 'long' | 'watch' | 'exit'
  strength?: number
  price?: number
  pct?: number
  provisional?: boolean
  triggered_at?: string
  triggeredAt?: string
  // 后端实际发的键（规则引擎口径），联调时对不上会表现为「流通了但一条不显示」。
  // SSE 用 rule，落库的历史行用 rule_id——两个都认。
  rule?: string
  rule_id?: string
  rule_label?: string
  at?: string
  symbol?: string
}

type RawSignalsPayload = {
  seq?: number
  as_of?: string
  asOf?: string
  items?: RawSignalItem[]
  /** 后端实际用的键；早期契约写的是 items，两个都认。 */
  signals?: RawSignalItem[]
}

/**
 * `hello` / `heartbeat` 帧：**没有行情时唯一说得出真相的那一帧**。
 *
 * 上游数据源挂掉时，SSE 依然 200、心跳照发、链路一切正常——旧版这时只发
 * `: keepalive` 注释，前端连「现在是不是开着盘」都不知道，于是一边显示「已连接」
 * 一边把早盘的数字冻到收盘。这一帧就是为这种时候存在的。
 */
export type StreamStatus = {
  preset: string
  session: { phase: string; live: boolean }
  /** 最近一帧行情的服务端时间；没有过就是空串 */
  asOf: string
  /** 距最近一次**成功**采集的毫秒数；`-1` = 从未成功过 */
  staleMs: number
  /** 采集器最近一次失败的原因；空串 = 数据源正常 */
  sourceError: string
  rows: number
  errors: number
}

type RawStreamStatus = {
  preset?: string
  session?: { phase?: string; live?: boolean }
  as_of?: string
  asOf?: string
  stale_ms?: number
  staleMs?: number
  source_error?: string
  sourceError?: string
  rows?: number
  errors?: number
}

function parseStreamStatus(raw: RawStreamStatus): StreamStatus {
  return {
    preset: String(raw.preset ?? ''),
    session: {
      phase: String(raw.session?.phase ?? 'closed'),
      live: Boolean(raw.session?.live ?? false),
    },
    asOf: String(raw.as_of ?? raw.asOf ?? ''),
    staleMs: Number(raw.stale_ms ?? raw.staleMs ?? -1),
    sourceError: String(raw.source_error ?? raw.sourceError ?? ''),
    rows: Number(raw.rows ?? 0),
    errors: Number(raw.errors ?? 0),
  }
}

function parseQuoteRow(raw: RawQuoteRow): QuoteRow {
  return {
    code: String(raw.code ?? ''),
    name: String(raw.name ?? ''),
    price: Number(raw.price ?? 0),
    prevClose: Number(raw.prev_close ?? raw.prevClose ?? 0),
    change: Number(raw.change ?? 0),
    pct: Number(raw.pct ?? 0),
    volume: Number(raw.volume ?? 0),
    amount: Number(raw.amount ?? 0),
    turnover: Number(raw.turnover ?? 0),
    amplitude: Number(raw.amplitude ?? 0),
    speed: Number(raw.speed ?? 0),
    high: Number(raw.high ?? 0),
    low: Number(raw.low ?? 0),
    open: Number(raw.open ?? 0),
    staleMs: Number(raw.stale_ms ?? raw.staleMs ?? 0),
  }
}

function parseQuoteFrame(raw: RawQuoteFrame): QuoteFrame {
  return {
    seq: Number(raw.seq ?? 0),
    asOf: String(raw.as_of ?? raw.asOf ?? ''),
    source: String(raw.source ?? 'stream'),
    session: {
      phase: String(raw.session?.phase ?? 'closed'),
      live: Boolean(raw.session?.live ?? false),
    },
    rows: Array.isArray(raw.rows) ? raw.rows.map(parseQuoteRow) : [],
  }
}

function parseSignalItem(raw: RawSignalItem): SignalItem {
  return {
    id: String(raw.id ?? ''),
    code: String(raw.code ?? raw.symbol ?? ''),
    name: String(raw.name ?? ''),
    // 后端字段是 rule / rule_label，前端类型沿用 strategy 命名。
    strategy: String(raw.strategy ?? raw.rule ?? raw.rule_id ?? ''),
    strategyName: String(
      raw.strategy_name ?? raw.strategyName ?? raw.rule_label ?? raw.strategy ?? raw.rule_id ?? '',
    ),
    title: String(raw.title ?? raw.rule_label ?? ''),
    detail: String(raw.detail ?? ''),
    direction: raw.direction === 'exit' ? 'exit' : raw.direction === 'watch' ? 'watch' : 'long',
    strength: Number(raw.strength ?? 0),
    price: Number(raw.price ?? 0),
    pct: Number(raw.pct ?? 0),
    // 历史行（signal_journal）不带这个键：它们已经落库定稿了。缺省按「已定稿」
    // 处理，别把复盘列表整片标成盘中未定稿。
    provisional: Boolean(raw.provisional ?? false),
    triggeredAt: String(raw.triggered_at ?? raw.triggeredAt ?? raw.at ?? ''),
  }
}

export function parseSseBlock(block: string): { type: string; data: unknown; id?: string } | null {
  const trimmed = block.trim()
  if (!trimmed || /^:\s*/.test(trimmed)) return null

  const type = block.match(/^event:\s*(.+)$/m)?.[1]?.trim() ?? 'message'
  const dataLines = [...block.matchAll(/^data:\s?(.*)$/gm)].map((m) => m[1] ?? '')
  if (!dataLines.length) return null

  const raw = dataLines.join('\n')
  if (raw === '[DONE]') return null

  let data: unknown
  try {
    data = JSON.parse(raw)
  } catch {
    data = { value: raw }
  }
  const id = block.match(/^id:\s*(.+)$/m)?.[1]?.trim()
  return { type, data, id }
}

export async function streamQuotes(opts: {
  preset: string
  codes?: string[]
  signal: AbortSignal
  onFrame: (f: QuoteFrame) => void
  /**
   * 链路已建立（HTTP 200 且是 event-stream）。**与「收到数据」是两件事**：
   * 上游数据源挂掉时后端仍会正常保持连接并发心跳，此时链路是好的、只是没数据。
   * 不区分这两者，界面就会把「数据源异常」误报成「连接中断」。
   */
  onOpen?: () => void
  /** `hello` / `heartbeat`：会话相位 + 数据源现状。没有行情时全靠它说话。 */
  onStatus?: (s: StreamStatus) => void
  onError?: (e: unknown) => void
}): Promise<void> {
  const params = new URLSearchParams()
  if (opts.preset) params.set('preset', opts.preset)
  if (opts.codes?.length) params.set('codes', opts.codes.join(','))

  const url = `/api/market/stream/quotes${params.toString() ? `?${params.toString()}` : ''}`
  try {
    const response = await fetch(url, {
      credentials: 'same-origin',
      headers: {
        Accept: 'text/event-stream',
        'Cache-Control': 'no-cache',
      },
      signal: opts.signal,
    })

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`)
    }
    if (!response.headers.get('content-type')?.includes('text/event-stream') || !response.body) {
      throw new Error('Not an event stream')
    }
    opts.onOpen?.()

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    try {
      for (;;) {
        const { value, done } = await reader.read()
        buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done })
        const frames = buffer.split(/\r?\n\r?\n/)
        buffer = frames.pop() ?? ''

        for (const frame of frames) {
          const parsed = parseSseBlock(frame)
          if (!parsed) continue
          if (parsed.type === 'hello' || parsed.type === 'heartbeat') {
            opts.onStatus?.(parseStreamStatus(parsed.data as RawStreamStatus))
            continue
          }
          if (parsed.type === 'snapshot' || parsed.type === 'patch' || parsed.type === 'message') {
            const quoteFrame = parseQuoteFrame(parsed.data as RawQuoteFrame)
            opts.onFrame(quoteFrame)
          }
        }

        if (done) break
      }
    } finally {
      reader.releaseLock()
    }
  } catch (err: unknown) {
    if (opts.signal.aborted) return
    opts.onError?.(err)
  }
}

export async function streamSignals(opts: {
  preset: string
  signal: AbortSignal
  onSignals: (items: SignalItem[], seq: number) => void
  /** 链路已建立；语义同 streamQuotes.onOpen */
  onOpen?: () => void
  /** `hello` / `heartbeat`；语义同 streamQuotes.onStatus */
  onStatus?: (s: StreamStatus) => void
  onError?: (e: unknown) => void
}): Promise<void> {
  const params = new URLSearchParams()
  if (opts.preset) params.set('preset', opts.preset)

  const url = `/api/market/stream/signals${params.toString() ? `?${params.toString()}` : ''}`
  try {
    const response = await fetch(url, {
      credentials: 'same-origin',
      headers: {
        Accept: 'text/event-stream',
        'Cache-Control': 'no-cache',
      },
      signal: opts.signal,
    })

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`)
    }
    if (!response.headers.get('content-type')?.includes('text/event-stream') || !response.body) {
      throw new Error('Not an event stream')
    }
    opts.onOpen?.()

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    try {
      for (;;) {
        const { value, done } = await reader.read()
        buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done })
        const frames = buffer.split(/\r?\n\r?\n/)
        buffer = frames.pop() ?? ''

        for (const frame of frames) {
          const parsed = parseSseBlock(frame)
          if (!parsed) continue
          if (parsed.type === 'hello' || parsed.type === 'heartbeat') {
            opts.onStatus?.(parseStreamStatus(parsed.data as RawStreamStatus))
            continue
          }
          // 后端事件名是 `signals`（复数），早期契约写的是 `signal`。两个都认——
          // 名字对不上时表现为「流是通的但一条都不显示」，是最难查的一类。
          if (parsed.type === 'signal' || parsed.type === 'signals' || parsed.type === 'message') {
            const payload = parsed.data as RawSignalsPayload
            const rawItems = Array.isArray(payload.items) ? payload.items : payload.signals
            const items = Array.isArray(rawItems)
              ? rawItems.map(parseSignalItem)
              : Array.isArray(parsed.data)
                ? (parsed.data as RawSignalItem[]).map(parseSignalItem)
                : []
            const seq = Number(payload.seq ?? 0)
            opts.onSignals(items, seq)
          }
        }

        if (done) break
      }
    } finally {
      reader.releaseLock()
    }
  } catch (err: unknown) {
    if (opts.signal.aborted) return
    opts.onError?.(err)
  }
}

/**
 * 信号历史（REST，非推流）：`GET /api/market/signals/recent`。
 *
 * 大屏首屏要有「刚才发生过什么」，而推流只会送**此刻之后**的新信号。以前这里
 * 是拿排行榜换个标签造几条假信号顶上，现在改成拉真引擎落下来的历史。
 * 服务端已按「7 天内 + 最多 80 条 + triggered_at 倒序」裁好，前端再兜一层
 * （见 useLiveBoard 的 SIGNAL_MAX_AGE_DAYS / SIGNAL_MAX_ITEMS）。
 */
export type RecentSignals = {
  items: SignalItem[]
  asOf: string
}

export async function getRecentSignals(limit = 80): Promise<RecentSignals> {
  const raw = await quantRequest<RawSignalsPayload>(`/market/signals/recent${query({ limit })}`)
  const rawItems = Array.isArray(raw?.items) ? raw.items : Array.isArray(raw?.signals) ? raw.signals : []
  return {
    items: rawItems.map(parseSignalItem),
    asOf: String(raw?.as_of ?? raw?.asOf ?? ''),
  }
}
