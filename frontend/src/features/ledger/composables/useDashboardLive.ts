import { computed, onMounted, onUnmounted, ref } from 'vue'

import { getLiveTape, type LiveTapeItem } from '@/shared/api/quant'
import { useLivePolling } from '@/shared/composables/useLivePolling'
import type { LiveReason } from '@/shared/lib/marketSession'
import type { Position } from '@/shared/types/palace'

export type LivePos = LiveTapeItem & { code: string }

export type PositionRow = Position & {
  last: number | null
  pct: number | null
  market_value: number | null
  float_pnl: number | null
  float_pnl_pct: number | null
  today_buy: number
  available: number
  live_ok: boolean
}

function round2(n: number): number {
  return Math.round(n * 100) / 100
}

function liveReasonLabel(reason: LiveReason | undefined): string {
  if (reason === 'non_trading_day') return '休市'
  if (reason === 'before_open') return '开盘前'
  if (reason === 'after_close_db_current') return '已收盘'
  if (reason === 'after_close_db_stale') return '已收盘·待补库'
  if (reason?.startsWith('after_close')) return '已收盘'
  return '库内'
}

export function useDashboardLive(positions: () => Position[]) {
  const liveByCode = ref<Record<string, LivePos>>({})
  const liveAsOf = ref('')
  const liveError = ref('')
  let lifecycleGeneration = 0

  onUnmounted(() => {
    lifecycleGeneration += 1
  })

  const positionRows = computed<PositionRow[]>(() => {
    const rows = positions().map((p) => {
      const live = liveByCode.value[p.code]
      const last = live?.price ?? null
      const costValue = p.cost_value
      const marketValue =
        last != null && p.shares ? round2(last * p.shares) : live?.market_value ?? null
      const floatPnl = marketValue != null ? round2(marketValue - costValue) : null
      const floatPct =
        live?.pnl_pct ??
        (last != null && p.cost ? round2((last / p.cost - 1) * 100) : null)
      const todayBuy = p.today_buy_shares ?? Math.max(0, p.shares - (p.available_shares ?? p.shares))
      const available = p.available_shares ?? Math.max(0, p.shares - todayBuy)
      return {
        ...p,
        last,
        pct: live?.pct ?? null,
        market_value: marketValue,
        float_pnl: floatPnl,
        float_pnl_pct: floatPct,
        today_buy: todayBuy,
        available,
        live_ok: Boolean(live?.ok),
      }
    })
    return rows.sort((a, b) => (b.market_value ?? b.cost_value) - (a.market_value ?? a.cost_value))
  })

  const liveMarketValue = computed(() => {
    const vals = positionRows.value.map((r) => r.market_value).filter((v): v is number => v != null)
    if (!vals.length) return null
    return round2(vals.reduce((a, b) => a + b, 0))
  })

  async function refreshLive(): Promise<void> {
    const generation = lifecycleGeneration
    try {
      const tape = await getLiveTape(true)
      if (generation !== lifecycleGeneration) return
      const map: Record<string, LivePos> = {}
      for (const item of tape.positions || []) {
        map[item.code] = item
      }
      liveByCode.value = map
      liveAsOf.value = tape.as_of || ''
      liveError.value = tape.error || ''
    } catch (caught: unknown) {
      if (generation !== lifecycleGeneration) return
      liveError.value = caught instanceof Error ? caught.message : '行情拉取失败'
    }
  }

  const { session, liveAllowed } = useLivePolling({ intervalMs: 8000, tick: refreshLive })

  const posLiveText = computed(() => {
    if (liveError.value) return liveError.value
    if (liveAllowed.value) {
      if (liveAsOf.value) return `实时 ${liveAsOf.value.slice(11, 19)}`
      return '行情接入中'
    }
    if (session.value?.live_reason) return liveReasonLabel(session.value.live_reason)
    return '读取会话…'
  })

  onMounted(() => {
    void refreshLive()
  })

  return {
    liveError,
    liveMarketValue,
    positionRows,
    posLiveText,
    round2,
  }
}
