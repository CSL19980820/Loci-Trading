/** 助手上下文用量估算（对齐 Cursor Context Usage 分段口径；粗估非计费）。 */

export type ContextUsageKind =
  | 'system'
  | 'tools'
  | 'rules'
  | 'memories'
  | 'mcp'
  | 'skill'
  | 'conversation'
  | 'draft'

export type ContextUsageSegment = {
  kind: ContextUsageKind
  label: string
  tokens: number
  color: string
}

export type ContextUsageSnapshot = {
  window: number
  used: number
  percent: number
  segments: ContextUsageSegment[]
  remaining: number
  /** 用量是否用供应商 input_tokens / 压缩后 feed 做过校准 */
  calibrated?: boolean
}

type CharCounts = { cjk: number; other: number }

function countChars(text: string): CharCounts {
  let cjk = 0
  let other = 0
  for (const char of text) {
    const code = char.codePointAt(0) ?? 0
    if (
      (code >= 0x4e00 && code <= 0x9fff)
      || (code >= 0x3400 && code <= 0x4dbf)
      || (code >= 0xf900 && code <= 0xfaff)
      || (code >= 0x3000 && code <= 0x303f)
    ) {
      cjk += 1
    } else {
      other += 1
    }
  }
  return { cjk, other }
}

function tokensFromCounts(cjk: number, other: number): number {
  if (cjk + other <= 0) return 0
  return Math.max(1, cjk + Math.floor((other + 3) / 4))
}

/** 与后端 `context_usage.estimate_tokens` 同口径。 */
export function estimateTokens(text: string | null | undefined): number {
  if (!text) return 0
  const { cjk, other } = countChars(text)
  return tokensFromCounts(cjk, other)
}

/** Cursor 风格：593 / 11.6K / 1.2M */
export function formatTokenCount(tokens: number): string {
  const value = Math.max(0, Math.floor(tokens))
  if (value < 1000) return String(value)
  if (value < 1_000_000) {
    const scaled = value / 1000
    if (Number.isInteger(scaled)) return `${scaled}K`
    return `${scaled.toFixed(1)}K`
  }
  const scaled = value / 1_000_000
  if (Number.isInteger(scaled)) return `${scaled}M`
  return `${scaled.toFixed(1)}M`
}

export const DEFAULT_CONTEXT_WINDOW = 128_000

/** Loci 安全底座粗估（与 domain assistant_system_prompt 同步量级；以 API 为准时可覆盖）。 */
export const CORE_SYSTEM_PROMPT_TOKENS = 280

/**
 * 定性分类色：只求八段互相可分，不承载涨跌 / 成败语义。
 * 具体色值定义在助手契约块（AssistantPanel.vue 的 unscoped `--ai-cat-*`），
 * 这里只返回引用，换主题 / 补深色适配不需要动这个文件。
 */
const SEGMENT_META: Record<ContextUsageKind, { label: string; color: string }> = {
  system: { label: '系统提示', color: 'var(--ai-cat-1)' },
  tools: { label: '工具定义', color: 'var(--ai-cat-2)' },
  rules: { label: '用户规则', color: 'var(--ai-cat-3)' },
  memories: { label: '跨会话记忆', color: 'var(--ai-cat-4)' },
  mcp: { label: 'MCP / 动态工具', color: 'var(--ai-cat-5)' },
  skill: { label: '激活技能', color: 'var(--ai-cat-6)' },
  conversation: { label: '会话正文', color: 'var(--ai-cat-7)' },
  draft: { label: '输入草稿', color: 'var(--ai-cat-8)' },
}

export type BuildContextUsageInput = {
  contextWindow?: number | null
  systemPromptTokens?: number | null
  aboutUser?: string
  responseStyle?: string
  rules?: string[]
  memories?: Array<{ content?: string }>
  tools?: Array<{
    name?: string
    description?: string
    tags?: string[]
    risk?: string
    /** 后端预估的完整 tools schema token，优先于 name/description 粗估 */
    schema_tokens?: number | null
  }>
  skillText?: string
  messages?: Array<{
    role?: string
    content?: string
    thinking?: string
    /** 来自 context_compacted.tokens_after，会话段用喂模后体积 */
    context_feed_tokens?: number | null
  }>
  draftText?: string
  /** 最近一轮供应商 input_tokens（校准总用量） */
  observedInputTokens?: number | null
}

function toolBlob(tool: {
  name?: string
  description?: string
  tags?: string[]
  risk?: string
}): string {
  return [tool.name, tool.description, tool.risk, ...(tool.tags || [])].filter(Boolean).join('\n')
}

function toolTokens(tool: {
  name?: string
  description?: string
  tags?: string[]
  risk?: string
  schema_tokens?: number | null
}): number {
  const schema = Number(tool.schema_tokens)
  if (Number.isFinite(schema) && schema > 0) return Math.floor(schema)
  return estimateTokens(toolBlob(tool))
}

function isMcpTool(tool: { name?: string; tags?: string[] }): boolean {
  const name = String(tool.name || '')
  const lower = name.toLowerCase()
  const tags = (tool.tags || []).map((tag) => String(tag).toLowerCase())
  // MCP 对外名多为 server__tool（见 tool_schema.mcp_tool_name）
  return (
    lower.includes('mcp')
    || name.includes('__')
    || tags.some((tag) => tag.includes('mcp') || tag === 'dynamic')
  )
}

type UsageMessage = NonNullable<BuildContextUsageInput['messages']>[number]

/**
 * 逐条消息缓存字符统计。
 *
 * 流式输出时每来一个 token 都要重算一次用量环，而历史消息一个字都没变——
 * 把整段会话拼成一个大字符串再逐字符扫，单轮回答就是 O(会话长度²)。
 * 缓存按消息对象身份存，字段用 `===` 比对（同一个字符串引用是 O(1)），
 * 于是只有正在生成的那一条会被重新计数。
 *
 * 存字符数而不是 token 数：token 公式带 `floor((other + 3) / 4)` 的取整，
 * 逐条算 token 再相加会和整段算的结果对不上；先合并字符数、最后套一次公式才等价。
 */
const MESSAGE_CHARS = new WeakMap<
  UsageMessage,
  { role?: string; content?: string; thinking?: string; counts: CharCounts }
>()

function messageCharCounts(row: UsageMessage): CharCounts {
  const cached = MESSAGE_CHARS.get(row)
  if (
    cached
    && cached.role === row.role
    && cached.content === row.content
    && cached.thinking === row.thinking
  ) {
    return cached.counts
  }
  const counts = countChars([row.role, row.content, row.thinking].filter(Boolean).join('\n'))
  MESSAGE_CHARS.set(row, { role: row.role, content: row.content, thinking: row.thinking, counts })
  return counts
}

function conversationTokens(rows: UsageMessage[]): number {
  let cjk = 0
  let other = 0
  rows.forEach((row, index) => {
    const counts = messageCharCounts(row)
    cjk += counts.cjk
    // 消息之间的 '\n\n' 也算在原口径里，补回来才与整段拼接等价
    other += counts.other + (index > 0 ? 2 : 0)
  })
  return tokensFromCounts(cjk, other)
}

export function buildContextUsage(input: BuildContextUsageInput): ContextUsageSnapshot {
  const window = Math.max(1024, Number(input.contextWindow) || DEFAULT_CONTEXT_WINDOW)
  const tools = input.tools || []
  const localTools = tools.filter((tool) => !isMcpTool(tool))
  const mcpTools = tools.filter((tool) => isMcpTool(tool))

  const systemExtra = [
    input.aboutUser ? `关于用户\n${input.aboutUser}` : '',
    input.responseStyle ? `回答偏好\n${input.responseStyle}` : '',
  ].filter(Boolean).join('\n\n')

  const rulesText = (input.rules || []).filter(Boolean).map((rule) => `- ${rule}`).join('\n')
  const memoriesText = (input.memories || [])
    .map((row) => String(row.content || '').trim())
    .filter(Boolean)
    .join('\n\n')
  let conversationUsed = conversationTokens(input.messages || [])
  // 压缩后：会话段改用喂模 feed 体积，环上 % 才能跟着掉
  const feedOverrides = (input.messages || [])
    .map((row) => Number(row.context_feed_tokens))
    .filter((value) => Number.isFinite(value) && value > 0)
  if (feedOverrides.length) {
    conversationUsed = Math.min(conversationUsed, Math.floor(feedOverrides[feedOverrides.length - 1]!))
  }

  const parts: Array<[ContextUsageKind, number]> = [
    ['system', (input.systemPromptTokens ?? CORE_SYSTEM_PROMPT_TOKENS) + estimateTokens(systemExtra)],
    ['tools', localTools.reduce((sum, tool) => sum + toolTokens(tool), 0)],
    ['rules', estimateTokens(rulesText)],
    ['memories', estimateTokens(memoriesText)],
    ['mcp', mcpTools.reduce((sum, tool) => sum + toolTokens(tool), 0)],
    ['skill', estimateTokens(input.skillText || '')],
    ['conversation', conversationUsed],
    ['draft', estimateTokens(input.draftText || '')],
  ]

  let segments: ContextUsageSegment[] = parts
    .filter(([, tokens]) => tokens > 0)
    .map(([kind, tokens]) => ({
      kind,
      label: SEGMENT_META[kind].label,
      tokens,
      color: SEGMENT_META[kind].color,
    }))

  let used = segments.reduce((sum, row) => sum + row.tokens, 0)
  let calibrated = false
  const observed = Number(input.observedInputTokens)
  // Cursor 口径：有真实 input_tokens 时按比例校准分段，使环上 used 贴近供应商
  if (Number.isFinite(observed) && observed > 0 && used > 0) {
    const target = Math.floor(observed)
    const scale = target / used
    segments = segments.map((row) => ({
      ...row,
      tokens: Math.max(1, Math.round(row.tokens * scale)),
    }))
    used = segments.reduce((sum, row) => sum + row.tokens, 0)
    calibrated = true
  }

  const percent = Math.min(100, Math.round((used / window) * 100))
  return {
    window,
    used,
    percent,
    segments,
    remaining: Math.max(0, window - used),
    calibrated,
  }
}
