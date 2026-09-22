import { compileStyle, parse } from '@vue/compiler-sfc'
import { afterEach, expect, it } from 'vitest'
import source from './MobileBottomNav.vue?raw'

afterEach(() => {
  document.documentElement.removeAttribute('data-mobile-keyboard')
  document.body.replaceChildren()
})

it('compiled keyboard rule hides only navigation and leaves the focused input visible', () => {
  const { descriptor } = parse(source)
  const style = descriptor.styles.find(block => block.scoped)!
  const compiled = compileStyle({ source: style.content, filename: 'MobileBottomNav.vue', id: 'data-v-mobile-nav', scoped: true })
  expect(compiled.errors).toEqual([])
  const css = compiled.code.replace(/\/\*[\s\S]*?\*\//g, '')
  const selectors = [...css.matchAll(/([^{}]+)\{\s*display:\s*none;?\s*\}/g)]
    .map(match => match[1]!.trim()).filter(selector => selector.includes('data-mobile-keyboard'))
  expect(selectors).toHaveLength(1)
  document.body.innerHTML = '<main><input id="account"></main><nav class="mobile-bottom-nav"></nav>'
  const input = document.querySelector<HTMLInputElement>('input')!
  input.focus()
  expect(document.querySelectorAll(selectors[0]!)).toHaveLength(0)
  document.documentElement.setAttribute('data-mobile-keyboard', '')
  expect([...document.querySelectorAll(selectors[0]!)]).toEqual([document.querySelector('nav')])
  expect(document.activeElement).toBe(input)
})
