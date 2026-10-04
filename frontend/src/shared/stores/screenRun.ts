/**
 * 选股后台任务：**每个战法一条进度**，全局单例轮询，不阻塞页面。
 *
 * 后端进度槽是「租户 × 战法」双层的（`src/strategy/application/screen_run_state.py`），
 * 所以这里也必须是字典：`runs[slug]`。历史上这个 store 只存一份 `snap`，于是
 * 「潜龙在跑」把所有战法的选股按钮全禁了，还挂着一句「引擎是后端全局单槽」的
 * 告示——那句话现在是假的，一并删掉。
 *
 * 只保留一条 progress 轮询：全部槽只传进度，新终态按战法补一次完整结果。
 */
import { defineStore } from 'pinia'
import { computed, onScopeDispose, ref, shallowRef } from 'vue'
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

const POLL_MS = 1200

/** 结果随该次运行的最后一次写入发布；重跑不能继承上一轮的结果。 */
function slotVersion(slot: ScreenRunSlot): string {
  return `${slot.started_at ?? 0}:${slot.updated_at ?? 0}`
}

function sameLog(left: string[], right: string[]): boolean {
  return left === right || (left.length === right.length && left.every((line, index) => line === right[index]))
}

/** 比较进度字段和日志，不遍历大结果数组。 */
function reuseSlot(previous: ScreenRunSlot | undefined, next: ScreenRunSlot): ScreenRunSlot {
  if (!previous) return next
  const keys = Object.keys(next) as (keyof ScreenRunSlot)[]
  const priorKeys = Object.keys(previous)
  if (keys.length !== priorKeys.length || previous.result !== next.result || !sameLog(previous.log, next.log)) return next
  return keys.every(key => key === 'log' || key === 'result' || previous[key] === next[key]) ? previous : next
}

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
  const runs = shallowRef<Record<string, ScreenRunSlot>>({})
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
  let snapshotRequest: { generation: number; promise: Promise<void> } | null = null
  let snapshotAt = 0
  let snapshotGeneration = -1
  const resultRequests = new Map<string, Promise<void>>()
  const loadedResults = new Map<string, string>()
  const resultInterests = new Set<string>()

  const runningStrategies = computed(() =>
    Object.entries(runs.value)
      .filter(([slug, slot]) => slug && slot.status === 'running')
      // 按后端 started_at 升序。聚合快照里槽的顺序是「最近碰过」的 LRU 序，会随
      // 每次轮询变动；chip 的主位不能随轮询换一个战法。
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
      const track = tracks.value[slug]
      if (!track?.exact || track.since !== authoritative) {
        tracks.value = { ...tracks.value, [slug]: { since: authoritative, exact: true } }
      }
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
      const previous = runs.value[slug]
      const version = slotVersion(slot)
      if (slot.status === 'done' && !slot.result_omitted && Object.hasOwn(slot, 'result')) loadedResults.set(slug, version)
      // progress 的缺字段不是清空；已取得同一版本的 full 后只复用本地结果。
      const loaded = loadedResults.get(slug) === version
      const sameVersion = previous && slot.updated_at !== undefined && previous.status === slot.status && slotVersion(previous) === version
      const result = slot.result_omitted
        ? loaded && sameVersion ? previous.result ?? null : null
        : sameVersion && previous.result_omitted !== true ? previous.result : slot.result
      const normalized = slot.result_omitted
        ? { ...slot, result, result_omitted: !loaded }
        : { ...slot, result }
      next[slug] = reuseSlot(previous, normalized)
      trackSlot(slug, slot)
      // 等新终态结果回来再提示，保留真实入库数量；初次水合不弹历史完成提示。
      if (!(slot.status === 'done' && slot.result_omitted && !loaded)) notify(slug, next[slug]!)
    }
    if (Object.keys(runs.value).length !== Object.keys(next).length || Object.keys(next).some(slug => runs.value[slug] !== next[slug])) {
      runs.value = next
    }
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
    loadedResults.delete(slug)
    resultInterests.add(slug)
    if (slot.status === 'done' && !slot.result_omitted && Object.hasOwn(slot, 'result')) loadedResults.set(slug, slotVersion(slot))
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

  function needsResult(slug: string, slot: ScreenRunSlot): boolean {
    return slot.status === 'done' && slot.result_omitted === true && loadedResults.get(slug) !== slotVersion(slot)
      && (resultInterests.has(slug) || lastStatus.get(slug) === 'running')
  }

  function needsPoll(): boolean {
    return running.value || Object.entries(runs.value).some(([slug, slot]) => needsResult(slug, slot))
  }

  /** 终态结果只读取一次；读结果不阻塞其它战法的进度请求。 */
  function loadResult(slug: string, slot: ScreenRunSlot, gen: number): Promise<void> {
    const version = slotVersion(slot)
    const key = `${gen}:${slug}:${version}`
    const pending = resultRequests.get(key)
    if (pending) return pending
    const task = (async () => {
      try {
        const full = await getScreenRunStatus({ strategy: slug })
        const current = runs.value[slug]
        if (gen !== pollGeneration || muted.has(slug) || !current || current.status !== 'done'
          || slotVersion(current) !== version || full.strategy !== slug || full.status !== 'done'
          || slotVersion(full) !== version || full.result_omitted) return
        loadedResults.set(slug, version)
        const resolved = { ...current, result: full.result ?? null, result_omitted: false }
        runs.value = { ...runs.value, [slug]: resolved }
        notify(slug, resolved)
        if (!needsPoll()) stopPoll()
      } catch {
        // progress 已到终态，结果读取失败仍需下轮重试。
      } finally {
        resultRequests.delete(key)
      }
    })()
    resultRequests.set(key, task)
    return task
  }

  /** App、页面水合和轮询共用同一代在途请求，只消费一次快照。 */
  function readSnapshot(gen: number): Promise<void> {
    if (snapshotRequest?.generation === gen) return snapshotRequest.promise
    let task!: Promise<void>
    task = (async () => {
      try {
        const payload = await getScreenRunStatus({ view: 'progress' })
        if (gen !== pollGeneration) return
        applySnapshot(payload)
        snapshotAt = Date.now()
        snapshotGeneration = gen
        for (const [slug, slot] of Object.entries(runs.value)) {
          if (needsResult(slug, slot)) void loadResult(slug, slot, gen)
        }
      } finally {
        if (snapshotRequest?.promise === task) snapshotRequest = null
      }
    })()
    snapshotRequest = { generation: gen, promise: task }
    return task
  }

  async function tick(gen: number): Promise<void> {
    if (gen !== pollGeneration) return
    try {
      await readSnapshot(gen)
      if (gen !== pollGeneration) return
      if (needsPoll()) {
        schedulePoll()
        return
      }
      stopPoll()
    } catch {
      if (gen !== pollGeneration) return
      if (needsPoll()) schedulePoll()
    }
  }

  function ensurePoll(): void {
    if (!needsPoll()) return
    if (timer || snapshotRequest?.generation === pollGeneration) return
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
    pollGeneration += 1
    stopPoll()
    ensurePoll()
  }

  async function hydrate(force = false): Promise<void> {
    const gen = pollGeneration
    // 页面晚于 App 挂载也复用同一轮采样，不能因路由多一个消费者就多一次 GET。
    if (!force && snapshotGeneration === gen && Date.now() - snapshotAt < POLL_MS) {
      if (needsPoll() && !timer && snapshotRequest?.generation !== gen) schedulePoll()
      return
    }
    try {
      await readSnapshot(gen)
      if (gen !== pollGeneration) return
      if (needsPoll() && !timer) schedulePoll()
    } catch {
      /* 启动时接口未就绪可忽略 */
    }
  }

  /** 只有当前查看的战法才恢复历史大结果；未见过的槽先共享一次 progress 水合。 */
  async function ensureResultFor(strategy: string): Promise<void> {
    const slug = String(strategy || '').trim()
    if (!slug) return
    resultInterests.add(slug)
    const gen = pollGeneration
    if (!runFor(slug)) await hydrate(true)
    if (gen !== pollGeneration) return
    const slot = runFor(slug)
    if (slot && needsResult(slug, slot)) await loadResult(slug, slot, gen)
    if (gen === pollGeneration && needsPoll() && !timer) schedulePoll()
  }

  onScopeDispose(() => {
    pollGeneration += 1
    stopPoll()
  })

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
    if (needsPoll()) ensurePoll()
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
    ensureResultFor,
    ensurePoll,
    stopPoll,
    start,
    abandon,
    dismissAbandoned,
  }
})
