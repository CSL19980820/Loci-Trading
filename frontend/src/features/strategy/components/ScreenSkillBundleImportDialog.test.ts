import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import type { CloneBundle } from '@/shared/lib/cloneBundle'

const api = vi.hoisted(() => ({
  getScreenSkills: vi.fn(),
  createScreenSkill: vi.fn(),
}))

vi.mock('@/shared/api/quant_strategy', () => api)
vi.mock('@/shared/lib/clipboard', () => ({ copyText: vi.fn().mockResolvedValue(true) }))

import ScreenSkillBundleImportDialog from './ScreenSkillBundleImportDialog.vue'

function bundle(): CloneBundle {
  return {
    publish_id: 'PUB-1',
    slug: 'ma-cross',
    title: '均线金叉',
    summary: '5 日线上穿 20 日线。',
    kind: 'screen',
    entry_timing: 'next_open',
    owner_name: '老王',
    version: 2,
    source_text: 'PICK: MA(CLOSE, 5) > MA(CLOSE, 20);\n',
    params: { fast: 5 },
    manifest: { backtest: { start: '2020-01-01', end: '2024-01-01', trades: 60 } },
    content_sha256: 'abc',
    imported_from: 'clone-export',
  }
}

/** el-dialog 的内容默认 teleport 到 body，断言直接看 document。 */
const stubs = {
  'el-dialog': {
    props: ['modelValue'],
    template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>',
  },
  'el-alert': { props: ['title'], template: '<div class="alert">{{ title }}</div>' },
  'el-tag': { template: '<span><slot /></span>' },
  'el-input': {
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template:
      '<textarea :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
  },
  'el-button': {
    props: ['disabled'],
    template: '<button :disabled="disabled"><slot /></button>',
  },
}

async function open(props: Record<string, unknown>) {
  const wrapper = mount(ScreenSkillBundleImportDialog, {
    props: { modelValue: false, ...props },
    global: { stubs },
  })
  await wrapper.setProps({ modelValue: true })
  await flushPromises()
  return wrapper
}

function buttonByText(wrapper: VueWrapper, text: string) {
  return wrapper.findAll('button').find((node) => node.text().includes(text))
}

describe('ScreenSkillBundleImportDialog', () => {
  it('把重建出来的战法摊开给用户看，并逐条列出没跟过来的东西', async () => {
    api.getScreenSkills.mockResolvedValue([{ slug: 'ma-cross' }])
    const wrapper = await open({ bundle: bundle() })
    const text = wrapper.text()

    // slug 撞名 → 递增，不覆盖本地那份
    expect(text).toContain('ma-cross-2')
    expect(text).toContain('已改名')
    // 重建出来的 manifest 三件套都在明面上
    expect(text).toContain('120')
    expect(text).toContain('PICK')
    // 原作者的回测证据要点名，并说清得自己重跑
    expect(text).toContain('2020-01-01 ~ 2024-01-01')
    expect(text).toContain('重跑回测')
    // 正文预览
    expect(text).toContain('MA(CLOSE, 5)')
  })

  it('导入成功后向上抛 imported', async () => {
    api.getScreenSkills.mockResolvedValue([])
    api.createScreenSkill.mockResolvedValue({ slug: 'ma-cross', name: '均线金叉' })
    const wrapper = await open({ bundle: bundle() })

    await buttonByText(wrapper, '导入到我的工坊')?.trigger('click')
    await flushPromises()

    const payload = api.createScreenSkill.mock.calls[0][0]
    expect(payload.slug).toBe('ma-cross')
    expect(payload.runtime).toBe('formula')
    expect(payload.manifest.params).toEqual({ fast: { type: 'int', default: 5 } })
    expect(api.createScreenSkill).toHaveBeenCalledTimes(1)
    expect(wrapper.emitted('imported')).toHaveLength(1)
  })

  it('导入失败时把后端原文带出来，不兜底成「操作没成功」', async () => {
    api.getScreenSkills.mockResolvedValue([])
    api.createScreenSkill.mockRejectedValue(new Error('公式编译失败：E_UNKNOWN_FUNC 未知函数 FOO'))
    const wrapper = await open({ bundle: bundle() })

    await buttonByText(wrapper, '导入到我的工坊')?.trigger('click')
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('E_UNKNOWN_FUNC')
    expect(text).not.toContain('操作没成功')
  })

  it('本地战法列表读不到时不挡住导入，只说明去重失效', async () => {
    api.getScreenSkills.mockRejectedValue(new Error('后端没起来'))
    const wrapper = await open({ bundle: bundle() })
    expect(wrapper.text()).toContain('后端没起来')
    expect(buttonByText(wrapper, '导入到我的工坊')?.attributes('disabled')).toBeUndefined()
  })

  it('粘贴模式：粘错了给具体原因，粘对了就能导入', async () => {
    api.getScreenSkills.mockResolvedValue([])
    const wrapper = await open({ paste: true })

    await wrapper.find('textarea').setValue('已复制克隆包到剪贴板')
    await flushPromises()
    expect(wrapper.text()).toContain('不是合法 JSON')
    expect(buttonByText(wrapper, '还没有可导入的克隆包')).toBeTruthy()

    await wrapper.find('textarea').setValue(JSON.stringify(bundle()))
    await flushPromises()
    expect(wrapper.text()).toContain('均线金叉')
    expect(buttonByText(wrapper, '导入到我的工坊')).toBeTruthy()
  })

  it('克隆包没有正文时拦在前面，并说明为什么', async () => {
    api.getScreenSkills.mockResolvedValue([])
    const wrapper = await open({ bundle: { ...bundle(), source_text: '' } })
    expect(wrapper.text()).toContain('正文是空的')
    expect(buttonByText(wrapper, '克隆包没有正文')?.attributes('disabled')).toBeDefined()
  })
})
