import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { APPEARANCE_OPTIONS, CUSTOM_PRIMARY_ID, PRIMARY_OPTIONS, PRIMARY_SCALE_VARS } from '@/shared/lib/theme'
import { useThemeStore } from '@/shared/stores/theme'
import ThemeDialog from './ThemeDialog.vue'

/** EP 弹窗默认懒渲染 + teleport，测试里换成直通壳，才能拿到内容 */
const STUBS = {
  ElDialog: { template: '<div><slot /><slot name="footer" /></div>' },
  ElButton: { template: '<button><slot /></button>' },
  ElTag: { template: '<span><slot /></span>' },
  ElColorPicker: {
    props: ['modelValue', 'predefine'],
    emits: ['change'],
    template: '<button class="picker" @click="$emit(\'change\', \'#FFFACD\')" />',
  },
}

function mountDialog() {
  return mount(ThemeDialog, { props: { modelValue: true }, global: { stubs: STUBS } })
}

describe('ThemeDialog', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    document.documentElement.removeAttribute('style')
  })

  it('三段齐全：外观（真实配色预览）/ 主色色板 / 自定义', () => {
    const wrapper = mountDialog()
    expect(wrapper.findAll('.appearance')).toHaveLength(APPEARANCE_OPTIONS.length)
    expect(wrapper.findAll('.swatch')).toHaveLength(PRIMARY_OPTIONS.length)
    expect(wrapper.find('.picker').exists()).toBe(true)
  // 预览不是单色圆点：每档都画了画布 + 面板两层真实底色
    const scene = wrapper.find('.appearance__scene')
    expect(scene.attributes('style')).toContain(APPEARANCE_OPTIONS[0].preview.canvas)
    expect(wrapper.find('.appearance__panel').attributes('style')).toContain(
      APPEARANCE_OPTIONS[0].preview.surface,
    )
  })

  it('点内置主色即时生效，且不留内联色阶', async () => {
    const wrapper = mountDialog()
    const store = useThemeStore()
    await wrapper.findAll('.swatch')[3]!.trigger('click')
    expect(store.primaryId).toBe(PRIMARY_OPTIONS[3]!.id)
    for (const name of PRIMARY_SCALE_VARS) {
      expect(document.documentElement.style.getPropertyValue(name)).toBe('')
    }
  })

  it('取色器选色 → 切到自定义 + 写内联色阶 + 亮出「已按对比度自动校正」', async () => {
    const wrapper = mountDialog()
    const store = useThemeStore()

    await wrapper.find('.picker').trigger('click')

    expect(store.primaryId).toBe(CUSTOM_PRIMARY_ID)
    expect(store.customColor).toBe('#fffacd')
    expect(document.documentElement.style.getPropertyValue('--seal')).toBe(store.customScale['--seal'])
    // 淡黄被压暗了，提示必须出现（≤ 12 字）
    const hint = wrapper.find('.custom-hint')
    expect(hint.text()).toBe('已按对比度自动校正')
    expect(hint.text().length).toBeLessThanOrEqual(12)
  })

  it('选了本来就达标的颜色时不误报校正', async () => {
    const wrapper = mountDialog()
    useThemeStore().setCustomPrimary(PRIMARY_OPTIONS[0]!.color)
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.custom-hint').text()).not.toBe('已按对比度自动校正')
  })

  it('v-model 契约不变：只 emit update:modelValue（AppSidebar 在用）', async () => {
    const wrapper = mountDialog()
    await wrapper.findAll('button').at(-1)!.trigger('click')
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
  })
})
