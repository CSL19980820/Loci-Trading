import createDOMPurify from 'dompurify'
import { marked } from 'marked'

marked.setOptions({ breaks: true, gfm: true })

const SAFE_URI = /^(?:(?:https?|mailto|tel):|[^a-z]|[a-z+.\-]+(?:[^a-z+.\-:]|$))/i
type PurifyInstance = ReturnType<typeof createDOMPurify>
let purify: PurifyInstance | null = null

function getPurify(): PurifyInstance | null {
  if (typeof window === 'undefined') return null
  if (!purify?.isSupported) purify = createDOMPurify(window)
  return purify.isSupported ? purify : null
}

function stripDangerousHtml(html: string): string {
  return html
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '')
    .replace(/\son[a-z]+\s*=\s*(".*?"|'.*?'|[^\s>]+)/gi, '')
    .replace(/\s(href|src|xlink:href)\s*=\s*(["']?)\s*javascript:[^"'>\s]*/gi, ' $1=$2#')
}

export function renderAnnouncementMarkdown(source: string): string {
  const text = source.trim()
  if (!text) return ''
  const html = marked.parse(text, { async: false }) as string
  const instance = getPurify()
  const cleaned = instance
    ? instance.sanitize(html, {
        USE_PROFILES: { html: true },
        FORBID_TAGS: ['style', 'form', 'input', 'button'],
        FORBID_ATTR: ['style'],
        ALLOW_DATA_ATTR: false,
        ALLOWED_URI_REGEXP: SAFE_URI,
      })
    : stripDangerousHtml(html)
  return stripDangerousHtml(cleaned)
}

/** Formats token number into readable compact string. */
export function formatTokens(num: number | undefined | null): string {
  if (num === undefined || num === null) return '0'
  if (num < 0) return '不限'
  if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`
  if (num >= 1_000) return `${(num / 1_000).toFixed(1)}k`
  return String(num)
}

/** Converts raw limit (-1 for unlimited) into UI display object. */
export function quotaToUiValue(val: number | undefined): { unlimited: boolean; value: number } {
  if (val === undefined || val < 0) {
    return { unlimited: true, value: 0 }
  }
  return { unlimited: false, value: val }
}

/** Converts UI limit selection to payload value (-1 for unlimited). */
export function uiValueToQuota(unlimited: boolean, value: number): number {
  return unlimited ? -1 : Math.max(0, Math.floor(value || 0))
}
