/** 企微选股推送模板：预设、规范化、前端即时预览（与后端口径对齐）。 */

export type WecomScreenPreset = 'default' | 'compact' | 'with_date' | 'custom'

export interface WecomScreenTemplate {
  preset: WecomScreenPreset
  header: string
  intro: string
  pick: string
  pick_no_pct: string
  skill_pick: string
  skill_pick_no_pct: string
  empty: string
  formal_empty: string
  watch_header: string
  watch_pick: string
  watch_pick_no_pct: string
  more: string
  quant_tag: string
  skills_tag: string
  max_picks: number
  show_watch_picks: boolean
}

export const WECOM_PRESET_OPTIONS: { value: WecomScreenPreset; label: string; hint: string }[] = [
  { value: 'default', label: '默认', hint: '标题 + 列表；技能涨跌幅后逗号说明' },
  { value: 'compact', label: '简洁', hint: '同默认技能行式' },
  { value: 'with_date', label: '含日期', hint: '标题下显示交易日' },
  { value: 'custom', label: '自定义', hint: '自己改文案' },
]

const PRESET_COPY: Record<Exclude<WecomScreenPreset, 'custom'>, Partial<WecomScreenTemplate>> = {
  default: {
    header: '【{title}】-{kind}',
    intro: '',
    pick: '📌 {name} {code} {pct}',
    pick_no_pct: '📌 {name} {code}',
    skill_pick: '📌 {name} {code} {pct}，{note}',
    skill_pick_no_pct: '📌 {name} {code}，{note}',
    empty: '📭 暂无符合条件的标的',
    formal_empty: '📭 正式精选 0 只',
    watch_header: '👀 低吸观察（不计正式胜率）',
    watch_pick: '▫️ {name} {code} {pct}',
    watch_pick_no_pct: '▫️ {name} {code}',
    more: '…另有 {n} 只',
  },
  compact: {
    header: '【{title}】-{kind}',
    intro: '',
    pick: '📌 {name} {code} {pct}',
    pick_no_pct: '📌 {name} {code}',
    skill_pick: '📌 {name} {code} {pct}，{note}',
    skill_pick_no_pct: '📌 {name} {code}，{note}',
    empty: '📭 暂无符合条件的标的',
    formal_empty: '📭 正式精选 0 只',
    watch_header: '👀 低吸观察（不计正式胜率）',
    watch_pick: '▫️ {name} {code} {pct}',
    watch_pick_no_pct: '▫️ {name} {code}',
    more: '…另有 {n} 只',
  },
  with_date: {
    header: '【{title}】-{kind}',
    intro: '📅 {date}',
    pick: '📌 {name} {code} {pct}',
    pick_no_pct: '📌 {name} {code}',
    skill_pick: '📌 {name} {code} {pct}，{note}',
    skill_pick_no_pct: '📌 {name} {code}，{note}',
    empty: '📭 暂无符合条件的标的',
    formal_empty: '📭 正式精选 0 只',
    watch_header: '👀 低吸观察（不计正式胜率）',
    watch_pick: '▫️ {name} {code} {pct}',
    watch_pick_no_pct: '▫️ {name} {code}',
    more: '…另有 {n} 只',
  },
}

export const DEFAULT_WECOM_SCREEN_TEMPLATE: WecomScreenTemplate = {
  preset: 'default',
  header: '【{title}】-{kind}',
  intro: '',
  pick: '📌 {name} {code} {pct}',
  pick_no_pct: '📌 {name} {code}',
  skill_pick: '📌 {name} {code} {pct}，{note}',
  skill_pick_no_pct: '📌 {name} {code}，{note}',
  empty: '📭 暂无符合条件的标的',
  formal_empty: '📭 正式精选 0 只',
  watch_header: '👀 低吸观察（不计正式胜率）',
  watch_pick: '▫️ {name} {code} {pct}',
  watch_pick_no_pct: '▫️ {name} {code}',
  more: '…另有 {n} 只',
  quant_tag: '量化',
  skills_tag: '技能',
  max_picks: 30,
  show_watch_picks: false,
}

const SKILL_NOTE_MAX = 40

const SAMPLE = {
  title: '潜龙拐点',
  date: '2026-07-30',
  picks: [
    { name: '龙星科技', code: '300105', pct: 1.5, note: '主线放量站上五日线' },
    { name: '上港集团', code: '600018', pct: 5, note: '回踩确认后温和放量' },
    { name: '平安银行', code: '000001', pct: null as number | null, note: '防御仓样本无涨幅字段' },
  ],
  watch_picks: [{ name: '中通客车', code: '000957', pct: 1.66 }],
}

export function normalizeWecomScreenTemplate(
  raw?: Partial<WecomScreenTemplate> | null,
): WecomScreenTemplate {
  const base: WecomScreenTemplate = { ...DEFAULT_WECOM_SCREEN_TEMPLATE, ...(raw || {}) }
  const preset = WECOM_PRESET_OPTIONS.some((o) => o.value === base.preset)
    ? base.preset
    : 'default'
  base.preset = preset
  base.max_picks = Math.max(1, Math.min(50, Number(base.max_picks) || 30))
  base.show_watch_picks = base.show_watch_picks === true
  base.header = String(base.header || DEFAULT_WECOM_SCREEN_TEMPLATE.header)
  base.intro = String(base.intro ?? DEFAULT_WECOM_SCREEN_TEMPLATE.intro)
  base.pick = String(base.pick || DEFAULT_WECOM_SCREEN_TEMPLATE.pick)
  base.pick_no_pct = String(base.pick_no_pct || DEFAULT_WECOM_SCREEN_TEMPLATE.pick_no_pct)
  base.skill_pick = String(base.skill_pick || DEFAULT_WECOM_SCREEN_TEMPLATE.skill_pick)
  base.skill_pick_no_pct = String(
    base.skill_pick_no_pct || DEFAULT_WECOM_SCREEN_TEMPLATE.skill_pick_no_pct,
  )
  base.empty = String(base.empty ?? DEFAULT_WECOM_SCREEN_TEMPLATE.empty)
  base.formal_empty = String(
    base.formal_empty ?? DEFAULT_WECOM_SCREEN_TEMPLATE.formal_empty,
  )
  base.watch_header = String(
    base.watch_header ?? DEFAULT_WECOM_SCREEN_TEMPLATE.watch_header,
  )
  base.watch_pick = String(
    base.watch_pick || DEFAULT_WECOM_SCREEN_TEMPLATE.watch_pick,
  )
  base.watch_pick_no_pct = String(
    base.watch_pick_no_pct || DEFAULT_WECOM_SCREEN_TEMPLATE.watch_pick_no_pct,
  )
  base.more = String(base.more ?? DEFAULT_WECOM_SCREEN_TEMPLATE.more)
  base.quant_tag = String(base.quant_tag || '量化')
  base.skills_tag = String(base.skills_tag || '技能')
  if (base.skills_tag.trim().toLowerCase() === 'skills') base.skills_tag = '技能'
  if (preset !== 'custom') {
    Object.assign(base, PRESET_COPY[preset])
  }
  return base
}

export function applyWecomPreset(
  current: WecomScreenTemplate,
  preset: WecomScreenPreset,
): WecomScreenTemplate {
  if (preset === 'custom') {
    return { ...current, preset: 'custom' }
  }
  return normalizeWecomScreenTemplate({ ...current, preset, ...PRESET_COPY[preset] })
}

function fill(pattern: string, values: Record<string, string>): string {
  let text = pattern || ''
  for (const [key, value] of Object.entries(values)) {
    text = text.split(`{${key}}`).join(value)
  }
  return text
}

function formatPct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return ''
  if (Math.abs(value - Math.round(value)) < 1e-9) return `${value >= 0 ? '+' : ''}${Math.round(value)}%`
  const text = (value >= 0 ? '+' : '') + value.toFixed(2).replace(/\.?0+$/, '')
  return `${text}%`
}

function clipNote(raw: string | null | undefined): string {
  const note = String(raw || '')
    .trim()
    .replace(/\s+/g, ' ')
  if (!note) return ''
  if (note.length <= SKILL_NOTE_MAX) return note
  return `${note.slice(0, SKILL_NOTE_MAX - 1)}…`
}

export function previewWecomScreenTemplate(
  raw: Partial<WecomScreenTemplate> | null | undefined,
  kind: 'quant' | 'skills' = 'quant',
): string {
  const tpl = normalizeWecomScreenTemplate(raw)
  const kindTag = kind === 'skills' ? tpl.skills_tag : tpl.quant_tag
  const skillMode = kind === 'skills'
  const lines: string[] = []
  const header = fill(tpl.header, {
    title: SAMPLE.title,
    kind: kindTag,
    date: SAMPLE.date,
    note: '',
  }).trim()
  if (header) lines.push(header)
  const intro = fill(tpl.intro, {
    title: SAMPLE.title,
    kind: kindTag,
    date: SAMPLE.date,
    note: '',
  }).replace(/\s+$/u, '')
  if (intro) lines.push(intro)

  let rendered = 0
  for (const pick of SAMPLE.picks) {
    if (rendered >= tpl.max_picks) break
    const pctText = formatPct(pick.pct)
    const note = skillMode ? clipNote(pick.note) : ''
    let rowTpl: string
    if (skillMode && note) {
      rowTpl = pctText ? tpl.skill_pick : tpl.skill_pick_no_pct
      if (!pctText && rowTpl.includes('{pct}')) rowTpl = tpl.skill_pick_no_pct
    } else {
      rowTpl = pctText ? tpl.pick : tpl.pick_no_pct
      if (!pctText && rowTpl.includes('{pct}')) rowTpl = tpl.pick_no_pct
    }
    const row = fill(rowTpl, {
      name: pick.name,
      code: pick.code,
      pct: pctText,
      note,
    }).trim()
    if (row) lines.push(row)
    rendered += 1
  }
  if (tpl.show_watch_picks && SAMPLE.watch_picks.length) {
    const watchHeader = tpl.watch_header.trim()
    if (watchHeader) lines.push(watchHeader)
    for (const pick of SAMPLE.watch_picks) {
      const pctText = formatPct(pick.pct)
      const rowTpl = pctText ? tpl.watch_pick : tpl.watch_pick_no_pct
      const row = fill(rowTpl, { name: pick.name, code: pick.code, pct: pctText, note: '' }).trim()
      if (row) lines.push(row)
    }
  }
  if (rendered === 0 && tpl.empty.trim()) lines.push(tpl.empty.trim())
  return lines.join('\n')
}

export function sameWecomScreenTemplate(a: WecomScreenTemplate, b: WecomScreenTemplate): boolean {
  const x = normalizeWecomScreenTemplate(a)
  const y = normalizeWecomScreenTemplate(b)
  return (
    x.preset === y.preset &&
    x.header === y.header &&
    x.intro === y.intro &&
    x.pick === y.pick &&
    x.pick_no_pct === y.pick_no_pct &&
    x.skill_pick === y.skill_pick &&
    x.skill_pick_no_pct === y.skill_pick_no_pct &&
    x.empty === y.empty &&
    x.formal_empty === y.formal_empty &&
    x.watch_header === y.watch_header &&
    x.watch_pick === y.watch_pick &&
    x.watch_pick_no_pct === y.watch_pick_no_pct &&
    x.more === y.more &&
    x.quant_tag === y.quant_tag &&
    x.skills_tag === y.skills_tag &&
    x.max_picks === y.max_picks &&
    x.show_watch_picks === y.show_watch_picks
  )
}
