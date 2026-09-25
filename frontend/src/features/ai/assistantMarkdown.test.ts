import { describe, expect, it } from 'vitest'
import { renderAssistantMarkdown } from './assistantMarkdown'

function rendered(source: string): HTMLDivElement {
  const element = document.createElement('div')
  element.innerHTML = renderAssistantMarkdown(source)
  return element
}

describe('assistant markdown', () => {
  it('preserves valid emphasis, link destinations, query strings and factual text', () => {
    const node = rendered('**众泰汽车 [000980](https://example.test/q/000980?date=2026-09-21&source=report)** 收 2.24）')
    expect(node.querySelector('strong')?.textContent).toBe('众泰汽车 000980')
    expect(node.querySelector('a')?.getAttribute('href')).toBe('https://example.test/q/000980?date=2026-09-21&source=report')
    expect(node.textContent).toContain('收 2.24）')
  })

  it('degrades only the verified historical URL placeholder without guessing the missing URL or emphasis', () => {
    const source = '**众泰汽车 [000980]([URL] 收 2.24）'
    const node = rendered(source)
    expect(node.textContent?.trim()).toBe('众泰汽车 000980（链接已隐藏） 收 2.24）')
    expect(node.querySelector('a')).toBeNull()
    expect(node.querySelector('strong')).toBeNull()
    expect(source).toBe('**众泰汽车 [000980]([URL] 收 2.24）')
  })

  it('keeps valid emphasis around a redacted link but never creates a relative placeholder link', () => {
    const node = rendered('**众泰汽车 [000980]([URL])** 收 2.24')
    expect(node.querySelector('strong')?.textContent).toBe('众泰汽车 000980（链接已隐藏）')
    expect(node.querySelector('a')).toBeNull()
  })

  it('does not alter code examples, escaped delimiters, ordinary incomplete links or literal stars', () => {
    const code = '**众泰汽车 [000980]([URL] 收 2.24）'
    expect(rendered('`' + code + '`').querySelector('code')?.textContent).toBe(code)
    expect(rendered('```text\n' + code + '\n```').querySelector('code')?.textContent?.trim()).toBe(code)
    expect(rendered('**进行中的 [链接](https://example.test').textContent?.trim()).toBe('**进行中的 [链接](https://example.test')
    expect(rendered('这里的 ** 是原始字符。').textContent?.trim()).toBe('这里的 ** 是原始字符。')
    expect(rendered(String.raw`\[示例]([URL]`).textContent?.trim()).toBe('[示例]([URL]')
  })

  it('keeps lists and neighboring valid formatting intact', () => {
    const node = rendered('- **众泰汽车 [000980]([URL] 收 2.24）\n- **完整的下一项**')
    expect(node.querySelectorAll('li')).toHaveLength(2)
    expect(node.querySelector('li')?.textContent).toBe('众泰汽车 000980（链接已隐藏） 收 2.24）')
    expect(node.querySelector('strong')?.textContent).toBe('完整的下一项')
  })

})
