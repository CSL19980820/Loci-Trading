/** Cursor-style slash trigger: `/query` alone on the current line (no other chars). */

export type SlashMatch = {
  query: string
  /** Index where the slash line starts within full text. */
  lineStart: number
}

export function detectSlashTrigger(text: string): SlashMatch | null {
  const value = String(text ?? '')
  const lines = value.split('\n')
  const last = lines[lines.length - 1] ?? ''
  const match = /^\/([^\s/]*)$/.exec(last)
  if (!match) return null
  // 左右无文字：本行只有 /query；允许上面有其它行
  const lineStart = value.length - last.length
  return { query: match[1] ?? '', lineStart }
}

export function applySlashSelection(
  text: string,
  match: SlashMatch,
  /** Replace slash line with this (usually empty). */
  replacement = '',
): string {
  const before = text.slice(0, match.lineStart)
  const afterSlashLine = text.slice(match.lineStart).split('\n').slice(1).join('\n')
  if (!replacement && !afterSlashLine) return before.replace(/\n$/, '')
  if (!replacement) return `${before}${afterSlashLine}`
  return `${before}${replacement}${afterSlashLine ? `\n${afterSlashLine}` : ''}`
}

export type SlashSkillItem = {
  slug: string
  name: string
  description?: string
  /** 内置斜杠命令（非技能包），如 /compact */
  builtin?: boolean
}

/** Cursor 风格内置命令；与技能并列出现在 / 菜单 */
export const BUILTIN_SLASH_COMMANDS: SlashSkillItem[] = [
  {
    slug: 'compact',
    name: '压缩上下文',
    description: '压缩喂给模型的较早对话（库内原文保留）',
    builtin: true,
  },
]

export function filterSlashSkills(items: SlashSkillItem[], query: string): SlashSkillItem[] {
  const q = query.trim().toLowerCase()
  const enabled = items.filter((item) => item.slug)
  if (!q) return enabled.slice(0, 12)
  return enabled
    .filter((item) => {
      const hay = `${item.slug} ${item.name} ${item.description ?? ''}`.toLowerCase()
      return hay.includes(q)
    })
    .slice(0, 12)
}
