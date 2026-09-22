/** 工作台右侧：Agent 技能后台跑 + 事件流 / HITL */
import { computed, onActivated, onDeactivated, onUnmounted, ref } from 'vue'
import { toast } from 'vue-sonner'

import {
  getSkillRun,
  getSkillRunEvents,
  replySkillRun,
  startSkillRun,
  type SkillRun,
} from '@/shared/api/quant'
import { toErrorMessage } from '@/shared/lib/errors'

import { formatSkillRunEvent } from './skillRunLog'

const LOG_CAP = 120
const ACTIVE_STATUSES = new Set(['running', 'queued', 'pending', 'waiting_reply', 'waiting_input'])

export function useWorkbenchSkillRun() {
  const skillBusy = ref(false)
  const skillRun = ref<SkillRun | null>(null)
  const skillLog = ref<string[]>([])
  const skillReply = ref('')
  const skillEventAfter = ref(0)
  const error = ref('')
  /** 技能跑起来的时刻；后端 run 里没有可靠的开始时间，这里只记前端观测点。 */
  const skillSince = ref(0)
  const skillNow = ref(Date.now())
  /** 前端放弃跟踪：后端没有中止技能的接口，那条 run 会继续跑。 */
  const skillAbandoned = ref(false)

  const skillElapsedText = computed(() => {
    if (!skillSince.value) return ''
    const total = Math.max(0, Math.floor((skillNow.value - skillSince.value) / 1000))
    if (total < 60) return `已跑 ${total} 秒`
    const minutes = Math.floor(total / 60)
    const seconds = total % 60
    return seconds ? `已跑 ${minutes} 分 ${seconds} 秒` : `已跑 ${minutes} 分`
  })

  let skillPoll: ReturnType<typeof setInterval> | null = null
  let terminalLogged = false
  let lifecycleGeneration = 0

  function stopPoll(): void {
    if (skillPoll) {
      clearInterval(skillPoll)
      skillPoll = null
    }
  }

  function invalidate(): void {
    lifecycleGeneration += 1
    stopPoll()
  }

  function pushLog(line: string): void {
    skillLog.value.push(line)
    if (skillLog.value.length > LOG_CAP) {
      skillLog.value = skillLog.value.slice(-LOG_CAP)
    }
  }

  function reset(): void {
    invalidate()
    skillBusy.value = false
    skillRun.value = null
    skillLog.value = []
    skillReply.value = ''
    skillEventAfter.value = 0
    error.value = ''
    terminalLogged = false
    skillSince.value = 0
    skillAbandoned.value = false
  }

  async function refreshEvents(runId: string, generation = lifecycleGeneration): Promise<void> {
    try {
      const batch = await getSkillRunEvents(runId, skillEventAfter.value)
      if (generation !== lifecycleGeneration) return
      skillEventAfter.value = batch.next_after
      for (const event of batch.events) {
        const line = formatSkillRunEvent(event as Record<string, unknown>)
        if (line) pushLog(line)
      }
    } catch {
      /* ignore */
    }
  }

  function beginPoll(runId: string, generation: number): void {
    stopPoll()
    skillPoll = setInterval(() => {
      if (generation !== lifecycleGeneration) return
      skillNow.value = Date.now()
      void refreshEvents(runId, generation)
      void (async () => {
        try {
          const next = await getSkillRun(runId)
          if (generation !== lifecycleGeneration) return
          skillRun.value = next
          const st = skillRun.value.status
          if (st === 'done') {
            if (!terminalLogged) {
              terminalLogged = true
              pushLog('■ 技能跑完')
            }
            stopPoll()
            skillBusy.value = false
            skillSince.value = 0
          } else if (st === 'error') {
            if (!terminalLogged) {
              terminalLogged = true
              const err = skillRun.value.error || '未知错误'
              pushLog(`✗ 技能失败 · ${err}`)
            }
            stopPoll()
            skillBusy.value = false
            skillSince.value = 0
          }
        } catch {
          /* ignore */
        }
      })()
    }, 800)
  }

  function resumePolling(): void {
    const run = skillRun.value
    if (!run?.id) return
    const st = String(run.status || '')
    if (!ACTIVE_STATUSES.has(st)) return
    lifecycleGeneration += 1
    const generation = lifecycleGeneration
    skillBusy.value = true
    if (!skillSince.value) skillSince.value = Date.now()
    skillNow.value = Date.now()
    void refreshEvents(run.id, generation)
    beginPoll(run.id, generation)
  }

  /**
   * 技能是否真的还在跑。`skillBusy` 只覆盖「请求在途」那几百毫秒，拿它当
   * 「运行中」会让跑道在后台还在推进时显示待命。
   */
  const skillActive = computed(() => {
    if (skillBusy.value) return true
    return ACTIVE_STATUSES.has(String(skillRun.value?.status || ''))
  })

  /**
   * 放弃跟踪这次技能运行。
   *
   * 后端没有中止 skill-run 的接口（`/api/skill-runs/{id}` 只有查询、事件与
   * 回复），所以这里只停轮询、清本地进度；那条 run 会继续跑到底。日志里照实写。
   */
  function abandon(): void {
    if (!skillActive.value) return
    invalidate()
    skillBusy.value = false
    skillAbandoned.value = true
    skillSince.value = 0
    pushLog('■ 已停止跟踪 · 该次技能仍在后台继续')
  }

  async function start(opts: {
    slug: string
    name: string
    provider: string
    date?: string
  }): Promise<boolean> {
    if (!opts.provider) {
      error.value = '请先在运维配置 LLM 供应商，再跑 Agent 技能'
      return false
    }
    skillBusy.value = true
    error.value = ''
    skillLog.value = []
    skillEventAfter.value = 0
    skillReply.value = ''
    terminalLogged = false
    lifecycleGeneration += 1
    const generation = lifecycleGeneration
    stopPoll()
    pushLog(`▶ 启动技能 · ${opts.name}`)
    skillSince.value = Date.now()
    skillNow.value = Date.now()
    skillAbandoned.value = false
    try {
      const started = await startSkillRun(opts.slug, {
        provider: opts.provider,
        config: opts.date ? { date: opts.date } : {},
        background: true,
      })
      if (generation !== lifecycleGeneration) return false
      skillRun.value = started.run
      if (started.run.id) {
        pushLog(`· 任务号 ${started.run.id.slice(0, 8)}…`)
        await refreshEvents(started.run.id, generation)
        if (generation !== lifecycleGeneration) return false
        beginPoll(started.run.id, generation)
      }
      toast.info(`已在后台跑技能：${opts.name}`)
      return true
    } catch (e: unknown) {
      if (generation !== lifecycleGeneration) return false
      error.value = toErrorMessage(e, '技能运行失败')
      pushLog(`✗ 启动失败 · ${error.value}`)
      return false
    } finally {
      if (generation === lifecycleGeneration) skillBusy.value = false
    }
  }

  async function reply(): Promise<void> {
    const run = skillRun.value
    if (!run?.id || !skillReply.value.trim()) return
    const generation = lifecycleGeneration
    const replyText = skillReply.value.trim()
    skillBusy.value = true
    try {
      pushLog(`↩ 发送回复 · ${replyText.slice(0, 48)}`)
      const next = await replySkillRun(run.id, replyText)
      if (generation !== lifecycleGeneration) return
      skillRun.value = next.run
      skillReply.value = ''
      await refreshEvents(run.id, generation)
      if (generation !== lifecycleGeneration) return
      const st = String(next.run.status || '')
      if (ACTIVE_STATUSES.has(st)) beginPoll(run.id, generation)
    } catch (e: unknown) {
      if (generation !== lifecycleGeneration) return
      error.value = toErrorMessage(e, '回复失败')
      pushLog(`✗ 回复失败 · ${error.value}`)
    } finally {
      if (generation === lifecycleGeneration) skillBusy.value = false
    }
  }

  onActivated(resumePolling)
  onDeactivated(invalidate)
  onUnmounted(invalidate)

  return {
    skillBusy,
    skillRun,
    skillLog,
    skillReply,
    error,
    skillActive,
    skillElapsedText,
    skillAbandoned,
    reset,
    start,
    reply,
    abandon,
    stopPoll,
    resumePolling,
  }
}
