/** 工作台右侧：Agent 技能后台跑 + 事件流 / HITL */
import { onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

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

export function useWorkbenchSkillRun() {
  const skillBusy = ref(false)
  const skillRun = ref<SkillRun | null>(null)
  const skillLog = ref<string[]>([])
  const skillReply = ref('')
  const skillEventAfter = ref(0)
  const error = ref('')
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
        skillPoll = setInterval(() => {
          if (generation !== lifecycleGeneration) return
          if (!started.run.id) return
          void refreshEvents(started.run.id, generation)
          void (async () => {
            try {
              const next = await getSkillRun(started.run.id)
              if (generation !== lifecycleGeneration) return
              skillRun.value = next
              const st = skillRun.value.status
              if (st === 'done') {
                if (!terminalLogged) {
                  terminalLogged = true
                  pushLog('■ 技能跑完')
                }
                stopPoll()
              } else if (st === 'error') {
                if (!terminalLogged) {
                  terminalLogged = true
                  const err = skillRun.value.error || '未知错误'
                  pushLog(`✗ 技能失败 · ${err}`)
                }
                stopPoll()
              }
            } catch {
              /* ignore */
            }
          })()
        }, 800)
      }
      ElMessage.info(`已在后台跑技能：${opts.name}`)
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
    } catch (e: unknown) {
      if (generation !== lifecycleGeneration) return
      error.value = toErrorMessage(e, '回复失败')
      pushLog(`✗ 回复失败 · ${error.value}`)
    } finally {
      if (generation === lifecycleGeneration) skillBusy.value = false
    }
  }

  onUnmounted(invalidate)

  return {
    skillBusy,
    skillRun,
    skillLog,
    skillReply,
    error,
    reset,
    start,
    reply,
    stopPoll,
  }
}
