import { beforeEach, describe, expect, it } from 'vitest'
import { KeepAlive, defineComponent, h, nextTick, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import { LIVE_INK_KEY, useBoardInk } from '../composables/useBoardInk'
import { useThemeStore } from '@/shared/stores/theme'

const Probe = defineComponent({
  setup() {
    const { inkOn, toggleInk } = useBoardInk()
    return { inkOn, toggleInk }
  },
  render() {
    return h('div', 'board')
  },
})

const root = document.documentElement

function setAppearance(id: string, dark: boolean): void {
  root.setAttribute('data-appearance', id)
  root.setAttribute('data-theme', id)
  root.classList.toggle('dark', dark)
}

describe('useBoardInk · 大屏不擅自改用户外观', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    setAppearance('paper', false)
  })

  it('默认不开：进大屏不动 <html>，用户选的外观原样留着', async () => {
    const wrapper = mount(Probe)
    await nextTick()

    expect(root.getAttribute('data-appearance')).toBe('paper')
    expect(root.classList.contains('dark')).toBe(false)

    wrapper.unmount()
    await nextTick()
    expect(root.getAttribute('data-appearance')).toBe('paper')
  })

  it('显式打开才钉墨黑；离开时交还给主题 store', async () => {
    const wrapper = mount(Probe)
    await nextTick()

    wrapper.vm.toggleInk()
    await nextTick()
    expect(root.getAttribute('data-appearance')).toBe('ink')
    expect(root.classList.contains('dark')).toBe(true)
    expect(localStorage.getItem(LIVE_INK_KEY)).toBe('1')

    wrapper.unmount()
    await nextTick()
    // store 里仍是 day（默认），所以交还后是 day 而不是「进来之前的 DOM 快照」
    expect(root.getAttribute('data-appearance')).toBe(useThemeStore().appearanceId)
    expect(root.classList.contains('dark')).toBe(false)
  })

  it('偏好记在 localStorage：下次进大屏直接是墨黑', async () => {
    localStorage.setItem(LIVE_INK_KEY, '1')

    const wrapper = mount(Probe)
    await nextTick()
    expect(root.getAttribute('data-appearance')).toBe('ink')

    wrapper.unmount()
    await nextTick()
  })

  it('KeepAlive 下切走就还原，切回来再钉一次', async () => {
    localStorage.setItem(LIVE_INK_KEY, '1')
    const alive = ref(true)
    const Host = defineComponent({
      setup() {
        return () => h(KeepAlive, null, { default: () => (alive.value ? h(Probe) : h('i')) })
      },
    })

    const wrapper = mount(Host)
    await nextTick()
    expect(root.getAttribute('data-appearance')).toBe('ink')

    /*
     * KeepAlive 下离开路由**不触发 onUnmounted**，只触发 onDeactivated。
     * 少了这一对钩子，整站会被大屏永久钉在墨黑里（上一轮的真实事故）。
     */
    alive.value = false
    await nextTick()
    expect(root.getAttribute('data-appearance')).not.toBe('ink')

    alive.value = true
    await nextTick()
    expect(root.getAttribute('data-appearance')).toBe('ink')

    wrapper.unmount()
    await nextTick()
    expect(root.getAttribute('data-appearance')).not.toBe('ink')
  })

  it('在大屏上改外观：暗色覆盖自动让位，不把用户的新选择回滚掉', async () => {
    localStorage.setItem(LIVE_INK_KEY, '1')
    const wrapper = mount(Probe)
    await nextTick()
    expect(root.getAttribute('data-appearance')).toBe('ink')

    // 用户在大屏上从侧栏「主题」换成暖纸
    useThemeStore().setAppearance('paper')
    await nextTick()
    expect(wrapper.vm.inkOn).toBe(false)
    expect(root.getAttribute('data-appearance')).toBe('paper')

    // 离开大屏不得把「暖纸」再改回去
    wrapper.unmount()
    await nextTick()
    expect(root.getAttribute('data-appearance')).toBe('paper')
  })
})
