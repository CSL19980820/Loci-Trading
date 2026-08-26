import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Skill } from '@/shared/types/quant'

const api = vi.hoisted(() => ({ getSkill: vi.fn() }))
vi.mock('@/shared/api/quant', () => ({ getSkill: api.getSkill }))

import SkillDetailDialog from './SkillDetailDialog.vue'

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function skill(slug: string): Skill {
  return {
    slug,
    name: slug,
    description: `${slug} description`,
    version: '1.0.0',
    install_path: `data/skills/${slug}`,
    source_filename: `${slug}.zip`,
    content_sha256: 'test-sha256',
    metadata: {},
    enabled: true,
    instructions: '',
    allowed_tools: [],
    tool_specs: [],
    mcp_servers: [],
  }
}

function mountDialog() {
  return mount(SkillDetailDialog, {
    props: { modelValue: true, skill: skill('old-skill') },
    global: {
      stubs: {
        'el-dialog': { template: '<div><slot /><slot name="footer" /></div>' },
        'el-tabs': { template: '<div><slot /></div>' },
        'el-tab-pane': { template: '<div><slot /></div>' },
        SkillJobConfigPanel: true,
        ManualInline: { props: ['text'], template: '<span>{{ text }}</span>' },
        'el-table': { props: ['data'], template: '<div>{{ JSON.stringify(data) }}<slot /></div>' },
        'el-table-column': { template: '<span><slot /></span>' },
        'el-tag': { template: '<span><slot /></span>' },
        'el-button': { template: '<button><slot /></button>' },
        'el-empty': { template: '<div><slot /></div>' },
      },
    },
  })
}

describe('SkillDetailDialog request ordering', () => {
  afterEach(() => vi.clearAllMocks())

  it('does not let an older manual response replace the selected skill', async () => {
    const oldBody = deferred<Record<string, unknown>>()
    const newBody = deferred<Record<string, unknown>>()
    api.getSkill.mockImplementation((slug: string) =>
      slug === 'old-skill' ? oldBody.promise : newBody.promise,
    )

    const wrapper = mountDialog()
    await wrapper.setProps({ skill: skill('new-skill') })
    newBody.resolve({ ...skill('new-skill'), instructions: 'new manual' })
    await flushPromises()
    oldBody.resolve({ ...skill('old-skill'), instructions: 'old manual' })
    await flushPromises()

    expect(wrapper.text()).toContain('new manual')
    expect(wrapper.text()).not.toContain('old manual')
    wrapper.unmount()
  })
})
