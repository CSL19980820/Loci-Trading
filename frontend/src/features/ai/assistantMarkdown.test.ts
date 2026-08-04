import { describe, expect, it } from 'vitest'

import { renderAssistantMarkdown } from './assistantMarkdown'

describe('renderAssistantMarkdown', () => {
  it('returns empty for blank source', () => {
    expect(renderAssistantMarkdown('   ')).toBe('')
  })

  it('strips script tags and dangerous html attributes', () => {
    const html = renderAssistantMarkdown('<script>alert(1)</script>\n\n<img src=x onerror="alert(1)">')
    expect(html.toLowerCase()).not.toContain('<script')
    expect(html.toLowerCase()).not.toContain('onerror')
  })

  it('neutralizes javascript urls in links', () => {
    const html = renderAssistantMarkdown('[x](javascript:alert(1))')
    expect(html.toLowerCase()).not.toMatch(/href\s*=\s*["']?\s*javascript:/)
  })

  it('keeps basic markdown structure', () => {
    const html = renderAssistantMarkdown('**粗体**\n\n- a\n- b')
    expect(html).toContain('<strong>')
    expect(html).toContain('<li>')
  })
})
