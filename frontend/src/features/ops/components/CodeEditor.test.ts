import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

const monaco = vi.hoisted(() => {
  let resolve!: () => void
  const ready = new Promise<void>((done) => {
    resolve = done
  })
  return {
    ready,
    resolve,
    editor: {
      create: vi.fn(),
      defineTheme: vi.fn(),
      setTheme: vi.fn(),
    },
  }
})

vi.mock('./monacoEnv', () => ({ ensureMonacoEnv: vi.fn() }))
vi.mock('monaco-editor-css', () => ({}))
vi.mock('monaco-editor', async () => {
  await monaco.ready
  return monaco
})

import CodeEditor from './CodeEditor.vue'

describe('CodeEditor lifecycle', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('does not create Monaco after the host is unmounted while loading', async () => {
    const wrapper = mount(CodeEditor, { props: { modelValue: '{}' } })
    wrapper.unmount()
    monaco.resolve()
    await flushPromises()

    expect(monaco.editor.create).not.toHaveBeenCalled()
  })
})
