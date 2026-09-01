/**
 * 跨上下文复制文本。
 *
 * 为什么不能只写 `navigator.clipboard.writeText`：Async Clipboard API 被规范标记为
 * `[SecureContext]`，**只有 HTTPS / localhost 才存在**。本站目前的访问方式里，
 * 纯 HTTP 域名、局域网 IP 直访、以后可能的内网部署都不是安全上下文，此时
 * `navigator.clipboard` 直接是 `undefined`，`.writeText` 会抛 `TypeError`——
 * 之前三个复制入口就是这样被 catch 吞掉、齐刷刷弹「复制失败」的。
 *
 * 所以保留 `document.execCommand('copy')` 回退。**它虽然已被标为 deprecated，
 * 但在非安全上下文里是唯一可用的复制路径，请勿当历史包袱删掉**；等到全站强制
 * HTTPS 且不再有 IP / 内网访问方式时再议。
 */

/** 回退用的隐藏 textarea：不可见但必须可选中。 */
function createHiddenTextarea(value: string): HTMLTextAreaElement {
  const area = document.createElement('textarea')
  area.value = value
  // readOnly 挡住移动端弹软键盘，但仍可被 select() 选中。
  area.readOnly = true
  area.setAttribute('aria-hidden', 'true')
  area.tabIndex = -1
  // 坑 1：不能用 `display:none` / `visibility:hidden` / `hidden`——那样的元素
  // 不参与选区，execCommand('copy') 会复制到空串。只能「渲染但看不见」。
  area.style.opacity = '0'
  area.style.pointerEvents = 'none'
  // 坑 2：不能用 `position:absolute; top:-9999px`——聚焦时浏览器会把页面滚上去。
  // `position:fixed` 贴在当前视口内，配合 1px 尺寸，用户察觉不到。
  area.style.position = 'fixed'
  area.style.top = '0'
  area.style.left = '0'
  area.style.width = '1px'
  area.style.height = '1px'
  area.style.padding = '0'
  area.style.border = 'none'
  area.style.outline = 'none'
  area.style.boxShadow = 'none'
  area.style.background = 'transparent'
  return area
}

/** 非安全上下文下的唯一路径：隐藏 textarea + `document.execCommand('copy')`。 */
function copyViaExecCommand(value: string): boolean {
  // happy-dom / 未来彻底移除该 API 的浏览器：直接判失败，不要抛。
  if (typeof document.execCommand !== 'function') return false

  const selection = document.getSelection()
  // 坑 3：选区会被我们的 select() 顶掉，先存下来，结束后原样还回去，
  // 否则用户「选中一段文字 → 点复制」之后他的选区就没了。
  const savedRanges: Range[] = []
  if (selection) {
    for (let index = 0; index < selection.rangeCount; index += 1) {
      savedRanges.push(selection.getRangeAt(index))
    }
  }
  const previousFocus = document.activeElement

  const area = createHiddenTextarea(value)
  document.body.appendChild(area)
  try {
    // preventScroll 再保一道：即便布局异常也不把页面滚到顶部。
    area.focus({ preventScroll: true })
    area.select()
    // iOS Safari 上 select() 不够，必须显式给范围。
    area.setSelectionRange(0, value.length)
    return document.execCommand('copy') === true
  } catch {
    return false
  } finally {
    // 坑 4：无论成败都要摘掉临时节点，绝不能留在 DOM 里。
    area.remove()
    if (selection) {
      selection.removeAllRanges()
      for (const range of savedRanges) selection.addRange(range)
    }
    if (previousFocus instanceof HTMLElement) previousFocus.focus({ preventScroll: true })
  }
}

/**
 * 复制文本到剪贴板，返回是否真的复制成功。
 *
 * 只负责复制，**不弹任何 UI 提示**——提示文案由各调用点自己决定。
 * 返回 `false` 时务必如实告知用户，不要假装成功。
 */
export async function copyText(value: string): Promise<boolean> {
  if (!value) return false

  // `isSecureContext === false` 时 clipboard 必然不可用，省一次必失败的调用；
  // 该字段本身缺失（非浏览器环境）时不做判断，交给下面的 try/catch 兜底。
  const secure = globalThis.isSecureContext !== false
  // lib.dom 把 navigator.clipboard 标成必然存在，但非安全上下文里它真的是 undefined。
  const clipboard: Clipboard | undefined = navigator.clipboard
  if (secure && typeof clipboard?.writeText === 'function') {
    try {
      await clipboard.writeText(value)
      return true
    } catch {
      // 权限被拒 / 文档失焦 / 浏览器实现差异：继续走回退，不直接判死。
    }
  }

  return copyViaExecCommand(value)
}
