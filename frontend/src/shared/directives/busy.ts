import { h, render, type ObjectDirective } from 'vue'
import { Spinner } from '@/shared/components/ui/spinner'

interface BusyState { overlay?: HTMLElement; position: string; aria: string | null }
const states = new WeakMap<HTMLElement, BusyState>()

function update(el: HTMLElement, value: unknown) {
  let state = states.get(el)
  if (!value) {
    if (!state) return
    if (state.overlay) { render(null, state.overlay); state.overlay.remove() }
    el.style.position = state.position
    if (state.aria === null) el.removeAttribute('aria-busy')
    else el.setAttribute('aria-busy', state.aria)
    el.classList.remove('is-busy')
    states.delete(el)
    return
  }
  if (state) return
  state = { position: el.style.position, aria: el.getAttribute('aria-busy') }
  if (getComputedStyle(el).position === 'static') el.style.position = 'relative'
  const overlay = document.createElement('div')
  overlay.className = 'busy-overlay'
  overlay.setAttribute('role', 'status')
  overlay.setAttribute('aria-label', '加载中')
  render(h(Spinner, { class: 'busy-overlay__spinner', 'aria-hidden': 'true' }), overlay)
  el.append(overlay)
  el.setAttribute('aria-busy', 'true')
  el.classList.add('is-busy')
  state.overlay = overlay
  states.set(el, state)
}

export const vBusy: ObjectDirective<HTMLElement, unknown> = {
  mounted: (el, binding) => update(el, binding.value),
  updated: (el, binding) => update(el, binding.value),
  beforeUnmount: el => update(el, false),
}
