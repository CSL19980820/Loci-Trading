import createDOMPurify from 'dompurify'
import { marked } from 'marked'

marked.setOptions({ breaks: true, gfm: true })

const SAFE_URI = /^(?:(?:https?|mailto|tel):|[^a-z]|[a-z+.\-]+(?:[^a-z+.\-:]|$))/i

type Purify = ReturnType<typeof createDOMPurify>
let purify: Purify | null = null

function getPurify(): Purify | null {
  if (typeof window === 'undefined') return null
  if (!purify?.isSupported) purify = createDOMPurify(window)
  return purify.isSupported ? purify : null
}

/** Last-resort strip when DOMPurify window binding is unavailable (e.g. some test envs). */
function stripDangerousHtml(html: string): string {
  return html
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '')
    .replace(/\son[a-z]+\s*=\s*(".*?"|'.*?'|[^\s>]+)/gi, '')
    .replace(/\s(href|src|xlink:href)\s*=\s*(["']?)\s*javascript:[^"'>\s]*/gi, ' $1=$2#')
}

/** Render assistant markdown into a sanitized HTML fragment. */
export function renderAssistantMarkdown(source: string): string {
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
