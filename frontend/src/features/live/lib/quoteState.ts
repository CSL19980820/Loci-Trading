import { shallowRef, triggerRef, type ShallowRef } from 'vue'
import type { QuoteRow } from '@/shared/api/marketStream'
import type { LiveTapeItem } from '@/shared/api/quant_market'
import type { BoardRow } from '@/shared/types/quant'

/*
 * 大屏的行情数据层：报价缓存、指数分时点列、四榜选取、后端行到 QuoteRow 的转换。
 *
 * 从 useLiveBoard 里拆出来的原因有两条：一是那个文件的职责是 SSE 编排与连接状态，
 * 数据结构的取舍（上限多少、并列怎么排）跟它是两件事；二是这些是纯数据逻辑，
 * 拆出来才能被单测直接喂帧，不必先 mount 一个宿主组件。
 */

/**
 * 报价缓存上限。
 *
 * `preset=all` 每帧至多 400 行（后端 `MAX_PRESET_CODES = 400`），成员随
 * `select_active_universe` 的日内轮换换血，而旧实现全程只 `set` 不 `delete`——
 * 挂机一天能从首屏约 145 条涨到上万条，纯属白占内存。
 *
 * 2000 = 五帧不重样的容量。大屏真正消费这份缓存的只有跑马灯前 60 条与涨跌分布
 * 的降级计数（分布优先走 `/market/distribution`），2000 条足够覆盖一天里反复
 * 活跃的那批票，同时把增长钉死成常数。
 *
 * 代价要说清楚：`quotesList.length`（状态栏的「标的数」）从此是**当前在册报价数**，
 * 不再是「累计见过多少只」。后者本来也不是盯盘该看的数。
 */
export const QUOTE_CACHE_MAX = 2000

/**
 * 触顶时一次砍掉的条数（= 一整帧）。
 *
 * 逐条淘汰会让「重建下标」每帧都跑一次 O(N)，把省下来的开销原样还回去；
 * 一次砍一帧的量，摊下来约 400 个新代码才重建一次。
 */
const QUOTE_CACHE_TRIM = 400

/** 四个榜单各取前 N 名 */
export const RANK_SIZE = 10

export interface QuoteCache {
  /** code → 最新报价。原地写入，靠 `triggerRef` 通知下游 */
  map: ShallowRef<Map<string, QuoteRow>>
  /**
   * 与 `map` 同内容的顺序数组，供整屏直接消费（HeatStrip 要全量、TickerTape 取
   * 前 60、状态栏取 length）。
   *
   * 页面侧原来是 `computed(() => Array.from(quotesMap.value.values()))`：每帧走一遍
   * Map 迭代器物化整份。这里改成内部维护顺序数组 + 下标表，一帧只动被刷新的那几行，
   * 发布时做一次 `slice()`。发布**新引用**是必须的——下游是 props，引用不变子组件
   * 的 computed 不会重算。
   */
  list: ShallowRef<QuoteRow[]>
  /** 并入一批报价：命中就地覆盖，新代码追加到尾部，触顶按首次出现顺序淘汰 */
  upsert(rows: QuoteRow[]): void
}

export function createQuoteCache(): QuoteCache {
  const map = shallowRef<Map<string, QuoteRow>>(new Map())
  const list = shallowRef<QuoteRow[]>([])
  /** 首次出现顺序的报价数组；跑马灯的次序稳定就靠它（不做 LRU 重排） */
  let ordered: QuoteRow[] = []
  /** code → 在 ordered 里的下标，把「刷新一行」做成 O(1) 覆盖 */
  const at = new Map<string, number>()

  function upsert(rows: QuoteRow[]): void {
    if (!rows.length) return
    const cache = map.value
    for (const row of rows) {
      const slot = at.get(row.code)
      if (slot === undefined) {
        at.set(row.code, ordered.length)
        ordered.push(row)
      } else {
        ordered[slot] = row
      }
      cache.set(row.code, row)
    }

    if (cache.size > QUOTE_CACHE_MAX) {
      const dropped = ordered.splice(0, cache.size - (QUOTE_CACHE_MAX - QUOTE_CACHE_TRIM))
      for (const row of dropped) cache.delete(row.code)
      at.clear()
      for (let i = 0; i < ordered.length; i += 1) at.set(ordered[i].code, i)
    }

    // shallowRef 本就不追踪内部变更，旧版每帧 new Map(...) 复制整份纯属自缚
    triggerRef(map)
    list.value = ordered.slice()
  }

  return { map, list, upsert }
}

/** 指数分时点列上限：3s 一帧，240 点约 12 分钟窗口 */
const MAX_TRAIL_POINTS = 240

export interface IndexTrails {
  /** code → 最近 MAX_TRAIL_POINTS 个真实点位 */
  trails: ShallowRef<Map<string, number[]>>
  /** 追加本帧点位；与上一点相同则不入列，免得平盘时白撑数组 */
  push(rows: QuoteRow[]): void
}

/**
 * 指数分时点列。
 *
 * sparkline 要的是一条**真实**走势——旧的 IndexMiniChart 在没有历史时用 sin()
 * 造过一条假曲线，那是在骗人。这里只累计推流真实到达的点，没有点就画平线。
 *
 * 原地 push + 越界 shift，末尾一次 `triggerRef`。旧版每帧「复制整个 Map + 每个
 * 指数复制两遍 240 点数组」≈ 3400 次数字拷贝，而这是 `shallowRef`，那份不可变
 * 换不来任何响应式正确性。下游 `IndexBar.cells` 会把点列复制一份再交给
 * `IndexSparkline`——它的 `series` computed 依赖 `props.points` 这个**引用**，
 * 原地改数组不会让它重画。
 */
export function createIndexTrails(): IndexTrails {
  const trails = shallowRef<Map<string, number[]>>(new Map())

  function push(rows: QuoteRow[]): void {
    if (!rows.length) return
    const map = trails.value
    let touched = false
    for (const row of rows) {
      if (!Number.isFinite(row.price) || row.price <= 0) continue
      const list = map.get(row.code)
      if (!list) {
        map.set(row.code, [row.price])
      } else {
        if (list[list.length - 1] === row.price) continue
        list.push(row.price)
        if (list.length > MAX_TRAIL_POINTS) list.shift()
      }
      touched = true
    }
    if (touched) triggerRef(trails)
  }

  return { trails, push }
}

/**
 * 单趟部分选择：只维护一个长度 ≤ limit 的有序小数组，不复制整份也不全排序。
 *
 * 旧写法是 `[...stocks].sort(...).slice(0, 10)`——400 行做 4 次、每 3 秒一轮，
 * 光比较就 ~1.4 万次，只为取 40 行。这里每个榜单一趟 O(n)，共 1600 次比较。
 *
 * `dir = -1` 取最小的 limit 个（跌幅榜）。相等时新元素排在既有元素**之后**——
 * 与 `Array.prototype.sort` 的稳定性一致，否则并列名次会每帧互换位置。
 * `NaN` 的 score 比不过任何数，只在候选不足 limit 时才占位；旧的全排序遇到
 * NaN 比较器是未定义行为，这里的口径反而更确定。
 */
export function topRows(
  rows: QuoteRow[],
  score: (row: QuoteRow) => number,
  dir: 1 | -1,
  limit: number,
): QuoteRow[] {
  const out: QuoteRow[] = []
  const keys: number[] = []
  for (const row of rows) {
    const key = score(row) * dir
    if (out.length >= limit && !(key > keys[limit - 1])) continue
    let slot = out.length < limit ? out.length : limit - 1
    if (out.length < limit) {
      out.push(row)
      keys.push(key)
    }
    while (slot > 0 && key > keys[slot - 1]) {
      keys[slot] = keys[slot - 1]
      out[slot] = out[slot - 1]
      slot -= 1
    }
    keys[slot] = key
    out[slot] = row
  }
  return out
}

/** 榜单/首屏样本的落库行 → 推流口径的 QuoteRow（`turnover` 后端给的是小数，×100 成百分比） */
export function boardRowToQuote(b: BoardRow): QuoteRow {
  const p = Number(b.price ?? b.local_close ?? 0)
  const pct = Number(b.pct ?? b.local_pct ?? 0)
  return {
    code: String(b.code || ''),
    name: String(b.name || ''),
    price: p,
    prevClose: Number(b.prev_close ?? (pct !== 0 && p > 0 ? p / (1 + pct / 100) : p)),
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
}

/** 首屏 live-tape 的指数项 → QuoteRow；只有点位与涨跌幅是真的，量额一律 0 不编 */
export function tapeIndexToQuote(item: LiveTapeItem): QuoteRow {
  const p = Number(item.price ?? 0)
  const pct = Number(item.pct ?? 0)
  return {
    code: item.code || '',
    name: item.name || item.label || '',
    price: p,
    prevClose: pct !== 0 && p > 0 ? p / (1 + pct / 100) : p,
    change: Number(item.change ?? 0),
    pct,
    volume: 0,
    amount: 0,
    turnover: 0,
    amplitude: 0,
    speed: 0,
    high: p,
    low: p,
    open: p,
    staleMs: 0,
  }
}
