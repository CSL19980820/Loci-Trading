import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import type { GuardianHistoryQuery, GuardianPage } from '@/shared/types/guardian'

export function guardianToday(now = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(now)
  const value = (name: string) => parts.find(p => p.type === name)!.value
  return `${value('year')}-${value('month')}-${value('day')}`
}
export function guardianDaysAgo(days: number, today = guardianToday()): string {
  const day = new Date(`${today}T00:00:00Z`)
  day.setUTCDate(day.getUTCDate() - days)
  return day.toISOString().slice(0, 10)
}
export type GuardianRange = Pick<GuardianHistoryQuery, 'start' | 'end' | 'limit' | 'keyword'> & { followToday?: boolean }

export function useGuardianHistory<T>(fetchPage: (query: GuardianHistoryQuery, signal?: AbortSignal) => Promise<GuardianPage<T>>, poll = true, initial: Partial<GuardianRange> = {}) {
  const today = guardianToday()
  const range = ref<GuardianRange>({ start: today, end: today, limit: 20, followToday: true, ...initial })
  const page = ref(1)
  const items = shallowRef<T[]>([])
  const total = ref(0)
  const loading = ref(false)
  const error = ref('')
  let controller: AbortController | undefined
  let timer: ReturnType<typeof setTimeout> | undefined
  let disposed = false
  let suspended = false
  let pollEpoch = 0
  const query = computed<GuardianHistoryQuery>(() => ({ start: range.value.start, end: range.value.end, limit: range.value.limit, offset: (page.value - 1) * range.value.limit, ...(range.value.keyword?.trim() ? { keyword: range.value.keyword.trim() } : {}) }))

  async function load(clear = false): Promise<void> {
    if (disposed || suspended) return
    controller?.abort()
    const request = new AbortController(); controller = request
    // 换页期间保留总数；清零会使分页器把第2页钳回第1页并发起反向请求。
    if (clear) items.value = []
    loading.value = true; error.value = ''
    try {
      const result = await fetchPage(query.value, request.signal)
      if (disposed || request.signal.aborted) return
      const lastPage = Math.max(1, Math.ceil(result.total / range.value.limit))
      if (page.value > lastPage) { page.value = lastPage; await load(true); return }
      items.value = result.items; total.value = result.total
    } catch (e) {
      if (!disposed && !request.signal.aborted) error.value = e instanceof Error ? e.message : String(e)
    } finally { if (controller === request) loading.value = false }
  }
  function apply(value: GuardianRange): void { range.value = { ...value }; page.value = 1; void load(true) }
  function changePage(value: number): void { page.value = value; void load(true) }
  function todayOnly(): void {
    const day = guardianToday(); apply({ start: day, end: day, limit: range.value.limit, followToday: true })
  }
  async function tick(): Promise<void> {
    const epoch = pollEpoch
    if (disposed || suspended) return
    const day = guardianToday()
    if (!document.hidden && !loading.value && page.value === 1) {
      if (range.value.followToday && range.value.end !== day) {
        range.value = { ...range.value, start: day, end: day }
        await load(true)
      } else if (range.value.end === day) await load()
    }
    if (!disposed && !suspended && poll && epoch === pollEpoch) timer = setTimeout(tick, 15000)
  }
  onMounted(() => { void load(); if (poll) timer = setTimeout(tick, 15000) })
  // KeepAlive hides panels without unmounting them. Stop their reads, retain their state.
  onDeactivated(() => { ++pollEpoch; suspended = true; controller?.abort(); loading.value = false; clearTimeout(timer) })
  onActivated(() => {
    if (!suspended || disposed) return
    suspended = false
    void load()
    if (poll) timer = setTimeout(tick, 15000)
  })
  onUnmounted(() => { disposed = true; controller?.abort(); clearTimeout(timer) })
  return { range, page, items, total, loading, error, load, apply, changePage, todayOnly }
}
