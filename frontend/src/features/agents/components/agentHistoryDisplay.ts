import createDOMPurify from 'dompurify'
import { Marked } from 'marked'
import type { AgentAction, AgentHistoryRow } from '@/shared/types/stock_agents'
import { actionName } from '../agentFormat'

export type AgentHistoryMode = 'today' | 'history'
export interface AgentHistoryStats { total_runs: number; history_kept: number; cleaned_runs: number }
const tradeKinds = new Set(['buy', 'add', 'sell', 'reduce', 'take_profit', 'stop_loss'])
const markdown = new Marked({ breaks: true, gfm: true, renderer: {
  // Model Markdown needs text, tables and links; embedded HTML has no role here.
  html: () => '', image: () => '',
  link({ href, tokens }) { return /^https?:\/\//i.test(href) ? false : this.parser.parseInline(tokens) },
} })
let purify: ReturnType<typeof createDOMPurify> | undefined

export function beijingToday(date = new Date()): string {
  return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(date)
}

export function executedTradeActions(row: Pick<AgentHistoryRow, 'actions'>): AgentAction[] {
  return (row.actions ?? []).filter(item => tradeKinds.has(item.action) &&
    (item.status === 'rejected' || (item.status === 'filled' && item.quantity > 0)))
}
export const isTradeActionKind = (action: string) => tradeKinds.has(action)

export function tradeActionLabel(item: AgentAction): string {
  return `${actionName(item.action)} ${item.name || item.code} · ${item.status === 'rejected' ? '拒单' : '已模拟成交'}`
}

const escapeHtml = (value: string) => value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

/** Stored model text is untrusted. Images and embedded content never load. */
export function renderAgentMarkdown(source: string): string {
  if (typeof window === 'undefined') return `<pre>${escapeHtml(source)}</pre>`
  if (!purify?.isSupported) purify = createDOMPurify(window)
  if (!purify.isSupported) return `<pre>${escapeHtml(source)}</pre>`
  return purify.sanitize(markdown.parse(source, { async: false }) as string, {
    USE_PROFILES: { html: true }, ALLOW_DATA_ATTR: false,
    FORBID_TAGS: ['img', 'style', 'form', 'input', 'button', 'iframe', 'video', 'audio'],
    FORBID_ATTR: ['style'], ALLOWED_URI_REGEXP: /^https?:\/\//i,
  })
}

/** A literal excerpt for the list, while the detail retains the complete source. */
export function diarySummary(source: string | undefined, limit = 180): string {
  if (!source?.trim()) return ''
  let text: string
  if (typeof DOMParser === 'undefined') {
    text = source.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').replace(/[*#`>]/g, '')
  } else {
    const document = new DOMParser().parseFromString(renderAgentMarkdown(source), 'text/html')
    document.querySelectorAll('p, li, h1, h2, h3, h4, h5, h6, tr, blockquote, pre').forEach(element => {
      element.prepend(document.createTextNode(' ')); element.append(document.createTextNode(' '))
    })
    text = document.body.textContent || ''
  }
  text = text.replace(/https?:\/\/[^\s<>]+/gi, '').replace(/\s+/g, ' ').trim()
  const characters = Array.from(text)
  return characters.length > limit ? `${characters.slice(0, Math.max(0, limit - 1)).join('').trimEnd()}…` : text
}
