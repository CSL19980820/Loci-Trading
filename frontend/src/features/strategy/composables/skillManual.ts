/** SKILL.md 正文轻量分块 + 行内强调。
 *
 * 不用第三方 markdown / 不用 `v-html`：块级按行切，行内只认
 * `**加粗**`、`*斜体*`、`` `代码` ``、`[文字](url)`。
 */

export type ManualBlock =
  | { type: 'heading'; level: number; text: string }
  | { type: 'code'; text: string; lang: string }
  | { type: 'list'; items: string[]; ordered: boolean }
  | { type: 'quote'; text: string }
  | { type: 'table'; rows: string[][] }
  | { type: 'paragraph'; text: string }

export type InlineSeg =
  | { type: 'text'; text: string }
  | { type: 'strong'; text: string }
  | { type: 'em'; text: string }
  | { type: 'code'; text: string }
  | { type: 'link'; text: string; href: string }

const HEADING = /^(#{1,6})\s+(.*)$/
const FENCE = /^```(\w*)\s*$/
const BULLET = /^\s*[-*+]\s+(.*)$/
const ORDERED = /^\s*\d+[.)]\s+(.*)$/
const QUOTE = /^>\s?(.*)$/
/** 只有分隔行（|---|:--:|）才算表格，避免把普通竖线句子误判 */
const TABLE_DIVIDER = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$/

/** 行内：代码 → 链接 → 加粗 → 斜体；按出现顺序吃 */
const INLINE =
  /(`+)([^`]*?)\1|\[([^\]]+)\]\(([^)\s]+)\)|\*\*([^*]+)\*\*|__([^_]+)__|(?<!\*)\*([^*\n]+)\*(?!\*)|(?<!_)_([^_\n]+)_(?!_)/g

function splitRow(line: string): string[] {
  return line
    .replace(/^\s*\|/, '')
    .replace(/\|\s*$/, '')
    .split('|')
    .map((cell) => cell.trim())
}

export function parseInline(source: string): InlineSeg[] {
  if (!source) return []
  const segs: InlineSeg[] = []
  let last = 0
  INLINE.lastIndex = 0
  let match = INLINE.exec(source)
  while (match) {
    if (match.index > last) {
      segs.push({ type: 'text', text: source.slice(last, match.index) })
    }
    if (match[1] != null) {
      segs.push({ type: 'code', text: match[2] ?? '' })
    } else if (match[3] != null) {
      segs.push({ type: 'link', text: match[3], href: match[4] ?? '' })
    } else if (match[5] != null) {
      segs.push({ type: 'strong', text: match[5] })
    } else if (match[6] != null) {
      segs.push({ type: 'strong', text: match[6] })
    } else if (match[7] != null) {
      segs.push({ type: 'em', text: match[7] })
    } else if (match[8] != null) {
      segs.push({ type: 'em', text: match[8] })
    }
    last = match.index + match[0].length
    match = INLINE.exec(source)
  }
  if (last < source.length) segs.push({ type: 'text', text: source.slice(last) })
  return segs.length ? segs : [{ type: 'text', text: source }]
}

export function parseSkillManual(source: string): ManualBlock[] {
  const lines = source.replace(/\r\n?/g, '\n').split('\n')
  const blocks: ManualBlock[] = []
  let paragraph: string[] = []

  const flushParagraph = (): void => {
    if (!paragraph.length) return
    blocks.push({ type: 'paragraph', text: paragraph.join(' ') })
    paragraph = []
  }

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i]

    const fence = FENCE.exec(line)
    if (fence) {
      flushParagraph()
      const body: string[] = []
      i += 1
      while (i < lines.length && !FENCE.test(lines[i])) {
        body.push(lines[i])
        i += 1
      }
      blocks.push({ type: 'code', text: body.join('\n'), lang: fence[1] })
      continue
    }

    if (!line.trim()) {
      flushParagraph()
      continue
    }

    const heading = HEADING.exec(line)
    if (heading) {
      flushParagraph()
      blocks.push({ type: 'heading', level: heading[1].length, text: heading[2].trim() })
      continue
    }

    if (line.includes('|') && TABLE_DIVIDER.test(lines[i + 1] ?? '')) {
      flushParagraph()
      const rows: string[][] = [splitRow(line)]
      i += 2
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) {
        rows.push(splitRow(lines[i]))
        i += 1
      }
      i -= 1
      blocks.push({ type: 'table', rows })
      continue
    }

    const quote = QUOTE.exec(line)
    if (quote) {
      flushParagraph()
      blocks.push({ type: 'quote', text: quote[1].trim() })
      continue
    }

    const bullet = BULLET.exec(line)
    const ordered = bullet ? null : ORDERED.exec(line)
    if (bullet || ordered) {
      flushParagraph()
      const isOrdered = !bullet
      const items: string[] = [(bullet ?? ordered)![1].trim()]
      while (i + 1 < lines.length) {
        const next = isOrdered ? ORDERED.exec(lines[i + 1]) : BULLET.exec(lines[i + 1])
        if (!next) break
        items.push(next[1].trim())
        i += 1
      }
      blocks.push({ type: 'list', items, ordered: isOrdered })
      continue
    }

    paragraph.push(line.trim())
  }

  flushParagraph()
  return blocks
}
