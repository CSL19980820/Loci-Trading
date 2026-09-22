import { onMounted, onUnmounted } from 'vue'
import { MOBILE_QUERY } from './useMobileLayout'

/** Keep navigation and dialogs within the visible viewport without disabling pinch zoom. */
export function useMobileViewport(): void {
  let frame = 0
  let largestHeight = 0
  let previousWidth = 0
  const editable = () => {
    const element = document.activeElement
    return element instanceof HTMLElement && (element.isContentEditable ||
      element.tagName === 'TEXTAREA' ||
      (element instanceof HTMLInputElement && !['checkbox', 'radio', 'range', 'button', 'submit'].includes(element.type)))
  }
  function update(): void {
    frame = 0
    const root = document.documentElement
    if (!window.matchMedia(MOBILE_QUERY).matches) {
      root.removeAttribute('data-mobile-keyboard')
      root.style.removeProperty('--mobile-viewport-height')
      root.style.removeProperty('--mobile-viewport-top')
      return
    }
    const viewport = window.visualViewport
    if (viewport && Math.abs(viewport.scale - 1) > .02) return
    const width = window.innerWidth
    const height = viewport?.height ?? window.innerHeight
    if (Math.abs(previousWidth - width) > 50) largestHeight = height
    previousWidth = width
    if (!editable()) largestHeight = Math.max(height, window.innerHeight)
    else largestHeight = Math.max(largestHeight, window.innerHeight)
    const keyboardOpen = editable() && largestHeight - height > 120
    root.toggleAttribute('data-mobile-keyboard', keyboardOpen)
    root.style.setProperty('--mobile-viewport-height', `${Math.round(height)}px`)
    root.style.setProperty('--mobile-viewport-top', `${Math.max(0, Math.round(viewport?.offsetTop ?? 0))}px`)
  }
  function schedule(): void {
    if (!frame) frame = requestAnimationFrame(update)
  }
  onMounted(() => {
    window.addEventListener('resize', schedule, { passive: true })
    window.visualViewport?.addEventListener('resize', schedule, { passive: true })
    window.visualViewport?.addEventListener('scroll', schedule, { passive: true })
    document.addEventListener('focusin', schedule)
    document.addEventListener('focusout', schedule)
    update()
  })
  onUnmounted(() => {
    cancelAnimationFrame(frame)
    window.removeEventListener('resize', schedule)
    window.visualViewport?.removeEventListener('resize', schedule)
    window.visualViewport?.removeEventListener('scroll', schedule)
    document.removeEventListener('focusin', schedule)
    document.removeEventListener('focusout', schedule)
    document.documentElement.removeAttribute('data-mobile-keyboard')
    document.documentElement.style.removeProperty('--mobile-viewport-height')
    document.documentElement.style.removeProperty('--mobile-viewport-top')
  })
}
