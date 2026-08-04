/** Skill 后台事件 → 中文进度日志（纯函数，便于单测） */

const PHASE_LABELS: Record<string, string> = {
  subagents: '并行弹药子任务',
  main_agent: '主脑推理',
  start: '启动',
  health: '体检',
  compute: '计算',
  persist: '入库',
  done: '收尾',
  error: '出错',
}

const STOP_LABELS: Record<string, string> = {
  completed: '正常完成',
  waiting_user: '等待你的回复',
  max_rounds: '达到轮数上限',
}

const TOOL_LABELS: Record<string, string> = {
  ask_user: '向你提问',
  write_journal: '写入技能日志',
  dispatch_subagents: '调度子任务',
}

const KIND_LABELS: Record<string, string> = {
  cli: '命令行',
  llm: '语言模型',
}

function phaseLabel(name: unknown): string {
  const key = String(name || '').trim()
  if (!key) return '未命名阶段'
  return PHASE_LABELS[key] || key
}

function stopLabel(reason: unknown): string {
  const key = String(reason || '').trim()
  if (!key) return '已结束'
  if (STOP_LABELS[key]) return STOP_LABELS[key]
  if (key.startsWith('llm_error:')) return `模型出错：${key.slice('llm_error:'.length).trim()}`
  return key
}

function toolLabel(name: unknown): string {
  const key = String(name || '').trim()
  if (!key) return '未知工具'
  return TOOL_LABELS[key] || key
}

function kindLabel(kind: unknown): string {
  const key = String(kind || '').trim().toLowerCase()
  if (!key) return ''
  return KIND_LABELS[key] || key
}

function clip(text: unknown, max = 72): string {
  const raw = String(text ?? '')
    .replace(/\s+/g, ' ')
    .trim()
  if (!raw) return ''
  return raw.length > max ? `${raw.slice(0, max - 1)}…` : raw
}

function argHint(argumentsValue: unknown): string {
  if (!argumentsValue || typeof argumentsValue !== 'object') return ''
  const args = argumentsValue as Record<string, unknown>
  const prompt = clip(args.prompt, 48)
  if (prompt) return prompt
  const date = String(args.date || '').trim()
  if (date) return `交易日 ${date}`
  const keys = Object.keys(args).slice(0, 3)
  if (!keys.length) return ''
  return keys.join('、')
}

/** 单条事件格式化为一条中文日志；无关事件返回 null */
export function formatSkillRunEvent(event: Record<string, unknown>): string | null {
  const type = String(event.type || '').trim()
  if (!type) return null

  if (type === 'phase') {
    return `▸ 进入阶段 · ${phaseLabel(event.name)}`
  }
  if (type === 'round_start') {
    const round = Number(event.round) || 0
    return round > 0 ? `◉ 第 ${round} 轮思考` : '◉ 开始思考'
  }
  if (type === 'subagent_start') {
    const id = String(event.id || '未命名').trim()
    const kind = kindLabel(event.kind)
    return kind ? `▷ 子任务启动 · ${id}（${kind}）` : `▷ 子任务启动 · ${id}`
  }
  if (type === 'subagent_end') {
    const id = String(event.id || '未命名').trim()
    const ok = Boolean(event.ok)
    const mark = ok ? '✓' : '✗'
    const preview = clip(event.preview, 64)
    const base = `${mark} 子任务${ok ? '完成' : '失败'} · ${id}`
    return preview ? `${base} · ${preview}` : base
  }
  if (type === 'tool_start') {
    const name = toolLabel(event.name)
    const hint = argHint(event.arguments)
    return hint ? `→ 调用 · ${name}（${hint}）` : `→ 调用 · ${name}`
  }
  if (type === 'tool_end') {
    const name = toolLabel(event.name)
    const ok = event.ok !== false
    const mark = ok ? '✓' : '✗'
    const preview = clip(event.preview, 64)
    const base = `${mark} ${ok ? '完成' : '失败'} · ${name}`
    return preview ? `${base} · ${preview}` : base
  }
  if (type === 'waiting_user') {
    const ask = event.ask && typeof event.ask === 'object' ? (event.ask as Record<string, unknown>) : null
    const prompt = clip(ask?.prompt, 64)
    return prompt ? `⏸ 等待你的回复 · ${prompt}` : '⏸ 等待你的回复…'
  }
  if (type === 'user_reply') {
    const text = clip(event.text, 48)
    return text ? `↩ 已收到回复 · ${text}` : '↩ 已收到你的回复'
  }
  if (type === 'done') {
    return `■ ${stopLabel(event.stopped_reason)}`
  }
  if (type === 'error') {
    const message = clip(event.message, 120) || '未知错误'
    return `✗ 错误 · ${message}`
  }
  return null
}
