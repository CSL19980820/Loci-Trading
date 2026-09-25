import createDOMPurify from 'dompurify'
import { Marked } from 'marked'

/**
 * Older stored messages replaced the URL and its adjacent Markdown delimiters
 * with [URL]. Only degrade that exact placeholder in ordinary text tokens:
 * the original destination/emphasis cannot be recovered from history.
 */
function readableRedactedText(text: string): string {
  return text.split('\n').map((line) => {
    const damagedLink = /\[([^\]\n]+)\]\(\[URL\](?!\))/g
    if (!damagedLink.test(line)) return line
    // A parsed strong token is already valid. This lone leading marker belongs
    // to the plain-text fallback of the old, unterminated emphasis.
    const plain = /^\s*\*\*/.test(line) && (line.match(/\*\*/g)?.length ?? 0) === 1
      ? line.replace(/^(\s*)\*\*/, '$1')
      : line
    return plain.replace(damagedLink, '$1（链接已隐藏）')
  }).join('\n')
}

const markdown = new Marked({
  breaks: true,
  gfm: true,
  walkTokens(token) {
    if (token.type === 'text' && !token.tokens && typeof token.text === 'string') {
      token.text = readableRedactedText(token.text)
    }
  },
  renderer: {
    link({ href, tokens }) {
      // A retained delimiter still does not turn a redaction marker into a URL.
      if (href === '[URL]') return `${this.parser.parseInline(tokens)}（链接已隐藏）`
      return false
    },
  },
})

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
  const html = markdown.parse(text, { async: false }) as string
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
