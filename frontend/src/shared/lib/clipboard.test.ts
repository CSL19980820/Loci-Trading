import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { copyText } from './clipboard'

const realClipboard = navigator.clipboard

function setClipboard(value: Clipboard | undefined): void {
  Object.defineProperty(navigator, 'clipboard', { value, configurable: true })
}

function setSecureContext(value: boolean | undefined): void {
  Object.defineProperty(globalThis, 'isSecureContext', { value, configurable: true })
}

/** happy-dom 没有 document.execCommand，装一个会记录「被复制到什么」的替身。 */
function stubExecCommand(succeed: boolean): { copied: () => string } {
  let copied = ''
  document.execCommand = vi.fn((command: string) => {
    if (command !== 'copy') return false
    const active = document.activeElement
    if (active instanceof HTMLTextAreaElement) copied = active.value
    return succeed
  })
  return { copied: () => copied }
}

/** 只做剪贴板写入的假 Clipboard，够 copyText 的 `typeof writeText === 'function'` 判断用。 */
function fakeClipboard(writeText: (text: string) => Promise<void>): Clipboard {
  const stub = { writeText } satisfies Pick<Clipboard, 'writeText'>
  // 测试替身：只实现被调用到的那个方法，其余成员用不到。
  return stub as Clipboard
}

describe('copyText', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })

  afterEach(() => {
    setClipboard(realClipboard)
    setSecureContext(undefined)
    Reflect.deleteProperty(document, 'execCommand')
    document.body.innerHTML = ''
    vi.restoreAllMocks()
  })

  it('非安全上下文（navigator.clipboard 为 undefined）时回退 execCommand 并复制到正确内容', async () => {
    setSecureContext(false)
    setClipboard(undefined)
    const exec = stubExecCommand(true)

    await expect(copyText('盈亏 +3.2% / 胜率 61%')).resolves.toBe(true)
    expect(exec.copied()).toBe('盈亏 +3.2% / 胜率 61%')
    expect(document.execCommand).toHaveBeenCalledWith('copy')
  })

  it('clipboard 可用时直接走它，不白白降级到 execCommand', async () => {
    setSecureContext(true)
    const writeText = vi.fn(async () => {})
    setClipboard(fakeClipboard(writeText))
    stubExecCommand(true)

    await expect(copyText('已复制的摘要')).resolves.toBe(true)
    expect(writeText).toHaveBeenCalledWith('已复制的摘要')
    expect(document.execCommand).not.toHaveBeenCalled()
  })

  it('clipboard 抛错（如权限被拒）时仍尝试回退', async () => {
    setSecureContext(true)
    const writeText = vi.fn(async () => {
      throw new DOMException('denied', 'NotAllowedError')
    })
    setClipboard(fakeClipboard(writeText))
    const exec = stubExecCommand(true)

    await expect(copyText('退而求其次')).resolves.toBe(true)
    expect(writeText).toHaveBeenCalledOnce()
    expect(exec.copied()).toBe('退而求其次')
  })

  it('两条路径都失败时返回 false，绝不假装成功', async () => {
    setSecureContext(true)
    setClipboard(fakeClipboard(async () => {
      throw new Error('boom')
    }))
    stubExecCommand(false)

    await expect(copyText('复制不上的文本')).resolves.toBe(false)
  })

  it('execCommand 本身不存在时返回 false 而不抛异常', async () => {
    setSecureContext(false)
    setClipboard(undefined)

    await expect(copyText('没有任何可用路径')).resolves.toBe(false)
  })

  it('空串直接判失败，不碰任何剪贴板 API', async () => {
    setSecureContext(true)
    const writeText = vi.fn(async () => {})
    setClipboard(fakeClipboard(writeText))
    stubExecCommand(true)

    await expect(copyText('')).resolves.toBe(false)
    expect(writeText).not.toHaveBeenCalled()
    expect(document.execCommand).not.toHaveBeenCalled()
  })

  it('无论成败都不把临时 textarea 留在 DOM 里', async () => {
    setSecureContext(false)
    setClipboard(undefined)

    stubExecCommand(true)
    await expect(copyText('成功路径')).resolves.toBe(true)
    expect(document.querySelectorAll('textarea')).toHaveLength(0)

    stubExecCommand(false)
    await expect(copyText('失败路径')).resolves.toBe(false)
    expect(document.querySelectorAll('textarea')).toHaveLength(0)

    document.execCommand = vi.fn(() => {
      throw new Error('execCommand exploded')
    })
    await expect(copyText('抛异常路径')).resolves.toBe(false)
    expect(document.querySelectorAll('textarea')).toHaveLength(0)
  })

  it('回退时恢复用户原有选区，并把焦点还给原来的元素', async () => {
    setSecureContext(false)
    setClipboard(undefined)
    stubExecCommand(true)

    const paragraph = document.createElement('p')
    paragraph.textContent = '用户先前选中的一段话'
    const input = document.createElement('input')
    document.body.append(paragraph, input)
    input.focus()

    const range = document.createRange()
    range.selectNodeContents(paragraph)
    const selection = document.getSelection()
    if (!selection) throw new Error('happy-dom 应当提供 Selection')
    selection.removeAllRanges()
    selection.addRange(range)
    // happy-dom 的 textarea.select() 不会真顶掉 document 选区，光断言选区内容
    // 「不恢复也能过」。所以这里盯的是「原 Range 确实被重新装回去了」。
    const addRange = vi.spyOn(selection, 'addRange')

    await expect(copyText('摘要正文')).resolves.toBe(true)

    expect(addRange).toHaveBeenCalledWith(range)
    expect(document.getSelection()?.getRangeAt(0).toString()).toBe('用户先前选中的一段话')
    expect(document.activeElement).toBe(input)
  })

  it('隐藏 textarea 不可见但可选中：opacity 而非 display:none，position:fixed 不滚页面', async () => {
    setSecureContext(false)
    setClipboard(undefined)
    const styles: Record<string, string> = {}
    document.execCommand = vi.fn(() => {
      const active = document.activeElement
      if (active instanceof HTMLTextAreaElement) {
        styles.display = active.style.display
        styles.visibility = active.style.visibility
        styles.opacity = active.style.opacity
        styles.position = active.style.position
      }
      return true
    })

    await expect(copyText('样式检查')).resolves.toBe(true)
    expect(styles).toEqual({
      display: '',
      visibility: '',
      opacity: '0',
      position: 'fixed',
    })
  })
})
