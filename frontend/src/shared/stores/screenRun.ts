/**
 * 选股后台任务：**每个战法一条进度**，全局单例轮询，不阻塞页面。
 *
 * 后端进度槽是「租户 × 战法」双层的（`src/strategy/application/screen_run_state.py`），
 * 所以这里也必须是字典：`runs[slug]`。历史上这个 store 只存一份 `snap`，于是
 * 「潜龙在跑」把所有战法的选股按钮全禁了，还挂着一句「引擎是后端全局单槽」的
 * 告示——那句话现在是假的，一并删掉。
 *
 * 只保留一条轮询：`GET /api/screen/run` 一次就返回全部槽，按战法各开一条轮询
 * 纯属自找 N 倍请求。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { toast } from 'vue-sonner'

import { cancelScreenRun, getScreenRunStatus, startScreenRun } from '@/shared/api/quant'
import { strategyLabel } from '@/shared/lib/format'
import type { ScreenResult, ScreenRunSlot, ScreenRunStatus } from '@/shared/types/quant'

export type ScreenStartOutcome = 'started' | 'busy' | 'error'

/**
 * 被用户停止的那一次选股（**按战法**记一条）。
 *
 * `stopping` 区分两种结局，**文案不能混用**：
 * - `true`：后端受理了停止请求（`POST /api/screen/run/cancel?strategy=`），会在下
 *   一个交易日检查点退出。当前这一个交易日仍会跑完并入库——取消是「不再往下
 *   跑」，不是「撤销已经做过的事」。
 * - `false`：请求没送达（老后端没这个端点，或网络断）。那条线程会跑到自己结束，
 *   所以文案只能写「已在后台继续」，不能写「已取消」。
 */
export interface AbandonedScreenRun {
  strategy: string
  /** 放弃那一刻的百分比；只作陈述，不再更新 */
  percent: number
  message: string
  at: number
  /** 后端是否受理了停止请求 */
  stopping: boolean
}

interface RunTrack {
  /** 这一轮的起点（ms）。后端给了 `started_at` 就是权威值 */
  since: number
  /** 起点是否权威；否则文案只能写「已跟踪」 */
  exact: boolean
}

const POLL_MS = 900

/** 「2 分 13 秒」——秒数进位成分钟，免得进度条旁边挂一串 3 位数秒。 */
function durationText(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  if (total < 60) return `${total} 秒`
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return seconds ? `${minutes} 分 ${seconds} 秒` : `${minutes} 分`
}

/** 老后端（没有 `runs`）的响应折成字典，前端逻辑只写一套。 */
function slotsOf(payload: ScreenRunStatus): Record<string, ScreenRunSlot> {
  if (payload.runs) return payload.runs
  const slug = String(payload.strategy || '')
  return slug ? { [slug]: payload } : {}
}

export const useScreenRunStore = defineStore('screenRun', () => {
  /** slug → 后端槽快照。跑完的槽也留着（前端要回看 picks） */
  const runs = ref<Record<string, ScreenRunSlot>>({})
  const tracks = ref<Record<string, RunTrack>>({})
  /** slug → 放弃跟踪的残影 */
  const abandonedRuns = ref<Record<string, AbandonedScreenRun>>({})
  const lastError = ref('')
  const now = ref(Date.now())
  /** 后端给的同时在跑上限（0 = 还不知道） */
  const maxConcurrentRuns = ref(0)

  /**
   * 已放弃跟踪、但后端还在跑的战法。轮询回来要**跳过**它们，否则用户点了停止
   * 之后下一次 tick 就把进度条又接回来了（老实现是靠停掉整条轮询回避这个问题，
   * 多槽下不能停——别的战法还在跑）。
   */
  const muted = new Set<string>()
  /** 上一轮各槽的 status，用来判「刚跑完」并只弹一次提示 */
  const lastStatus = new Map<string, string>()

  let timer: number | undefined
  let pollGeneration = 0

  const runningStrategies = computed(() =>
    Object.entries(runs.value)
      .filter(([slug, slot]) => slug && slot.status === 'running')
      // 按后端 started_at 升序。聚合快照里槽的顺序是「最近碰过」的 LRU 序，会随
      // 每次轮询变动；chip 的主位不能每 900ms 换一个战法。
      .sort((a, b) => Number(a[1].started_at || 0) - Number(b[1].started_at || 0))
      .map(([slug]) => slug),
  )
  /** 有**任何**战法在跑。注意：它不再是「能不能开新选股」的判据 */
  const running = computed(() => runningStrategies.value.length > 0)
  const busyStrategy = computed(() => runningStrategies.value[0] ?? '')

  /** 「当前这一个」槽：正在跑的第一个，否则最近更新过的那个。只用于全局提示 */
  const snap = computed<ScreenRunSlot | null>(() => {
    const focused = busyStrategy.value
    if (focused) return runs.value[focused] ?? null
    const entries = Object.values(runs.value)
    if (!entries.length) return null
    return entries.reduce((best, slot) =>
      Number(slot.updated_at || 0) >= Number(best.updated_at || 0) ? slot : best,
    )
  })
  const percent = computed(() => Math.round(Number(snap.value?.percent || 0)))
  const result = computed(() => (snap.value?.result as ScreenResult | null) ?? null)

  /** 最近一条残影：全局 chip 与 App.vue 的状态轨用它 */
  const abandoned = computed<AbandonedScreenRun | null>(() => {
    const entries = Object.values(abandonedRuns.value)
    if (!entries.length) return null
    return entries.reduce((latest, item) => (item.at >= latest.at ? item : latest))
  })

  function runFor(strategy: string): ScreenRunSlot | null {
    return runs.value[String(strategy || '')] ?? null
  }

  function isRunning(strategy: string): boolean {
    return runFor(strategy)?.status === 'running'
  }

  function percentFor(strategy: string): number {
    return Math.round(Number(runFor(strategy)?.percent || 0))
  }

  function resultFor(strategy: string): ScreenResult | null {
    return (runFor(strategy)?.result as ScreenResult | null) ?? null
  }

  function elapsedMsFor(strategy: string): number {
    const track = tracks.value[String(strategy || '')]
    if (!isRunning(strategy) || !track?.since) return 0
    return Math.max(0, now.value - track.since)
  }

  /** 「已跑 2 分 13 秒」/「已跟踪 2 分 13 秒」——后者表示起点只是下限。 */
  function elapsedTextFor(strategy: string): string {
    const track = tracks.value[String(strategy || '')]
    if (!isRunning(strategy) || !track?.since) return ''
    return `${track.exact ? '已跑' : '已跟踪'} ${durationText(elapsedMsFor(strategy))}`
  }

  /** 「潜龙出海 · 已跑 2 分 13 秒 · 42% · 扫描候选」——给忙提示直接用。 */
  function detailFor(strategy: string): string {
    const slot = runFor(strategy)
    if (!slot || slot.status !== 'running') return ''
    const parts = [strategyLabel(strategy) || '未知战法']
    const elapsed = elapsedTextFor(strategy)
    if (elapsed) parts.push(elapsed)
    parts.push(`${percentFor(strategy)}%`)
    const message = String(slot.message || '').trim()
    if (message) parts.push(message)
    return parts.join(' · ')
  }

  /** 正在跑的战法中文名，用于「先停一个」这类提示 */
  const runningLabels = computed(() =>
    runningStrategies.value.map((slug) => strategyLabel(slug) || slug).join('、'),
  )

  /** 并发到顶：不是「引擎忙」，是排队 */
  const atCapacity = computed(
    () =>
      maxConcurrentRuns.value > 0 &&
      runningStrategies.value.length >= maxConcurrentRuns.value,
  )

  /**
   * 这个战法现在能不能开跑。
   *
   * 只有两种不能：**它自己**在跑（防重复入库），或本账号并发到顶。别的战法在跑
   * 一律放行——这正是本次多槽改造的目的。
   */
  function canStart(strategy: string): boolean {
    if (isRunning(strategy)) return false
    return !atCapacity.value
  }

  /** 这个战法为什么开不了；空串 = 能开。按钮 tooltip 直接用 */
  function blockedReason(strategy: string): string {
    if (isRunning(strategy)) return `这个战法正在选股：${detailFor(strategy)}`
    if (atCapacity.value) {
      return `同时最多 ${maxConcurrentRuns.value} 个选股在跑（${runningLabels.value}），先停一个或等一个跑完`
    }
    return ''
  }

  function abandonedFor(strategy: string): AbandonedScreenRun | null {
    return abandonedRuns.value[String(strategy || '')] ?? null
  }

  function trackSlot(slug: string, slot: ScreenRunSlot): void {
    if (slot.status !== 'running') {
      if (tracks.value[slug]) {
        const next = { ...tracks.value }
        delete next[slug]
        tracks.value = next
      }
      return
    }
    const authoritative = Number(slot.started_at || 0) * 1000
    if (authoritative > 0) {
      tracks.value = { ...tracks.value, [slug]: { since: authoritative, exact: true } }
      return
    }
    // 老后端没有 started_at：只能记「前端什么时候开始看见它在跑」，文案降级成
    // 「已跟踪」。别谎报「已跑 0 秒」。
    if (!tracks.value[slug]) {
      tracks.value = { ...tracks.value, [slug]: { since: Date.now(), exact: false } }
    }
  }

  /** 跑完/失败弹一次轻提示（不抢前台；用户可在工作台看结果） */
  function notify(slug: string, slot: ScreenRunSlot): void {
    const prev = lastStatus.get(slug)
    lastStatus.set(slug, String(slot.status || ''))
    if (prev !== 'running') return
    const label = strategyLabel(slug) || slug
    if (slot.status === 'done') {
      const body = slot.result as ScreenResult | null
      const written =
        body?.recorded?.written_total ?? body?.recorded?.written ?? body?.range?.written_total
      const days = body?.range?.trading_days
      toast.success(
        written != null
          ? days && days > 1
            ? `区间选股完成 · ${days} 日 · 入库合计 ${written} 条 · ${label}`
            : `选股完成并入库 ${written} 条 · ${label}`
          : `选股完成 · ${label}`,
      )
      return
    }
    if (slot.status === 'error') {
      toast.error(slot.error || slot.message || `选股失败 · ${label}`)
    }
  }

  function applySnapshot(payload: ScreenRunStatus): void {
    const incoming = slotsOf(payload)
    const next: Record<string, ScreenRunSlot> = {}
    for (const [slug, slot] of Object.entries(incoming)) {
      if (!slug) continue
      if (muted.has(slug)) {
        // 还在跑 = 用户已放弃跟踪，不复活；跑完了就静默收尾（不弹完成提示）
        if (slot.status === 'running') continue
        muted.delete(slug)
        lastStatus.set(slug, String(slot.status || ''))
        continue
      }
      next[slug] = slot
      trackSlot(slug, slot)
      notify(slug, slot)
    }
    runs.value = next
    if (payload.max_concurrent_runs) {
      maxConcurrentRuns.value = Number(payload.max_concurrent_runs)
    }
    now.value = Date.now()
  }

  /** 单槽响应（`POST /api/screen/run`）就地合并，不动别的战法 */
  function mergeSlot(slot: ScreenRunSlot): void {
    const slug = String(slot.strategy || '')
    if (!slug) return
    muted.delete(slug)
    runs.value = { ...runs.value, [slug]: slot }
    trackSlot(slug, slot)
    lastStatus.set(slug, String(slot.status || ''))
    if (slot.max_concurrent_runs) maxConcurrentRuns.value = Number(slot.max_concurrent_runs)
    now.value = Date.now()
  }

  function stopPoll(): void {
    if (timer) {
      window.clearTimeout(timer)
      timer = undefined
    }
  }

  function schedulePoll(): void {
    stopPoll()
    const gen = pollGeneration
    timer = window.setTimeout(() => {
      void tick(gen)
    }, POLL_MS)
  }

  async function tick(gen: number): Promise<void> {
    if (gen !== pollGeneration) return
    try {
      const next = await getScreenRunStatus()
      if (gen !== pollGeneration) return
      applySnapshot(next)
      if (running.value) {
        schedulePoll()
        return
      }
      stopPoll()
    } catch {
      if (gen !== pollGeneration) return
      schedulePoll()
    }
  }

  function ensurePoll(): void {
    if (!running.value) return
    if (timer) return
    pollGeneration += 1
    void tick(pollGeneration)
  }

  /**
   * 起完一条之后立刻重同步。
   *
   * 在途那次 tick 可能是**这次 start 之前**发出的：它回来时聚合快照里还没有刚起
   * 的这条，`applySnapshot` 会按服务端真相把它抹掉一拍（进度条闪一下再回来）。
   * 换 generation 把它丢掉，并立刻补一次——`screen_run_try_begin` 是在 POST 里
   * 同步占槽的，所以下一次 GET 一定看得见它。
   */
  function resyncPoll(): void {
    stopPoll()
    ensurePoll()
  }

  async function hydrate(): Promise<void> {
    try {
      const next = await getScreenRunStatus()
      applySnapshot(next)
      if (running.value) ensurePoll()
    } catch {
      /* 启动时接口未就绪可忽略 */
    }
  }

  /**
   * 停止某个战法的选股：先请求后端中止，再把它从本地进度里摘掉。
   *
   * 后端的取消是**协作式**的（只立一面旗，真正的退出发生在交易日循环头的检查点
   * 上），所以：
   *
   * - 已经跑完的交易日**不回滚**，那些候选是真实发生过的选股结果；
   * - 从点下去到线程真的停下，最长是一个交易日的选股耗时；
   * - 请求打不通时**不把本地状态留在原地**——用户点了停止，界面就该停。此时退回
   *   旧的「只放弃跟踪」语义，文案照实说后台还在跑。
   *
   * **只影响这一个战法**：别的战法照旧跑、照旧轮询。
   */
  async function abandon(strategy?: string): Promise<void> {
    const slug = String(strategy || busyStrategy.value || '')
    if (!slug || !isRunning(slug)) return
    const wasPercent = percentFor(slug)

    let serverStopping = false
    try {
      const res = await cancelScreenRun(slug)
      serverStopping = Boolean(res.cancelled)
    } catch {
      // 后端够不着（老版本没有这个端点 / 网络断），退回纯前端放弃。
      serverStopping = false
    }

    abandonedRuns.value = {
      ...abandonedRuns.value,
      [slug]: {
        strategy: slug,
        percent: wasPercent,
        message: serverStopping
          ? '已请求停止，正在跑的这一个交易日会先跑完'
          : '没能通知到后端，这一轮会在后台跑完',
        at: Date.now(),
        stopping: serverStopping,
      },
    }

    muted.add(slug)
    lastStatus.delete(slug)
    const nextRuns = { ...runs.value }
    delete nextRuns[slug]
    runs.value = nextRuns
    const nextTracks = { ...tracks.value }
    delete nextTracks[slug]
    tracks.value = nextTracks
    lastError.value = ''

    // generation 一变，在途那次 tick 即使拿到响应也会被丢弃
    pollGeneration += 1
    stopPoll()
    // 别的战法还在跑就继续轮询——单槽时代这里是无条件停掉整条轮询
    if (running.value) ensurePoll()
  }

  function dismissAbandoned(strategy?: string): void {
    const slug = String(strategy || '')
    if (!slug) {
      abandonedRuns.value = {}
      return
    }
    const next = { ...abandonedRuns.value }
    delete next[slug]
    abandonedRuns.value = next
  }

  async function start(payload: {
    strategy: string
    date?: string
    start?: string
    end?: string
    record_candidates?: boolean
    top_n?: number
  }): Promise<ScreenStartOutcome> {
    lastError.value = ''
    const slug = String(payload.strategy || '')

    // 同一战法重复点击：本地先拦，省一次必然 202-busy 的往返
    if (isRunning(slug)) {
      lastError.value = `${blockedReason(slug)}，可等它结束或先停止它`
      return 'busy'
    }
    if (atCapacity.value) {
      lastError.value = blockedReason(slug)
      return 'busy'
    }

    try {
      const next = await startScreenRun({
        record_candidates: true,
        ...payload,
      })
      mergeSlot(next)

      if (next.busy_reason === 'tenant_limit') {
        const cap = Number(next.max_concurrent_runs || maxConcurrentRuns.value || 0)
        lastError.value = cap
          ? `同时最多 ${cap} 个选股在跑（${runningLabels.value}），先停一个或等一个跑完`
          : '选股并发已到上限，先停一个或等一个跑完'
        resyncPoll()
        return 'busy'
      }

      if (next.busy_reason === 'same_strategy') {
        // 多半是之前放弃跟踪的那次还在跑；既然又要看，就重新接上
        dismissAbandoned(slug)
        lastError.value = `${blockedReason(slug)}，可等它结束或先停止它`
        resyncPoll()
        return 'busy'
      }

      // 老后端没有 busy_reason：只能靠「返回的是别人的快照」判断被占
      if (next.status === 'running' && next.strategy && next.strategy !== slug) {
        dismissAbandoned(next.strategy)
        lastError.value = `选股进行中：${detailFor(next.strategy)}，请等待结束或放弃跟踪`
        resyncPoll()
        return 'busy'
      }

      if (next.status === 'running') {
        dismissAbandoned(slug)
        resyncPoll()
        return 'started'
      }

      if (next.status === 'error') {
        lastError.value = next.error || next.message || '选股失败'
        return 'error'
      }

      dismissAbandoned(slug)
      return 'started'
    } catch (caught: unknown) {
      lastError.value = caught instanceof Error ? caught.message : '启动选股失败'
      return 'error'
    }
  }

  return {
    // 状态
    runs,
    tracks,
    abandonedRuns,
    lastError,
    maxConcurrentRuns,
    // 聚合视图（全局 chip / 状态轨用）
    running,
    runningStrategies,
    runningLabels,
    atCapacity,
    busyStrategy,
    snap,
    percent,
    result,
    abandoned,
    // 按战法查询
    runFor,
    isRunning,
    percentFor,
    resultFor,
    elapsedMsFor,
    elapsedTextFor,
    detailFor,
    canStart,
    blockedReason,
    abandonedFor,
    // 动作
    hydrate,
    ensurePoll,
    stopPoll,
    start,
    abandon,
    dismissAbandoned,
  }
})
