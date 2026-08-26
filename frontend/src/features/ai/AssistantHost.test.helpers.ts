import { mount } from '@vue/test-utils'
import { afterEach, vi } from 'vitest'
import { ElMessageBox } from 'element-plus'

import {
  cancelAiRun,
  createAiSession,
  deleteAiSession,
  getAiRun,
  getAiRunEvents,
  getAiSession,
  getAiTools,
  listAiSessions,
  sendAiMessage,
  streamAiRunEvents,
} from '@/shared/api/ai_assistant'

const { routerPush } = vi.hoisted(() => ({ routerPush: vi.fn() }))

vi.mock('@/shared/api/ai_assistant', () => ({
  cancelAiRun: vi.fn(),
  createAiSession: vi.fn(),
  deleteAiSession: vi.fn(),
  getAiRun: vi.fn(),
  getAiRunEvents: vi.fn(),
  getAiSession: vi.fn(),
  getAiTools: vi.fn(),
  getAiProfile: vi.fn(),
  listAiMemories: vi.fn(),
  listAiSessions: vi.fn(),
  sendAiMessage: vi.fn(),
  compactAiSession: vi.fn(),
  streamAiRunEvents: vi.fn(),
  patchAiSession: vi.fn(),
  batchAiSessions: vi.fn(),
}))

vi.mock('vue-router', () => ({ useRouter: () => ({ push: routerPush }) }))

vi.mock('element-plus', async (importOriginal) => {
  const actual = await importOriginal<typeof import('element-plus')>()
  return {
    ...actual,
    ElMessageBox: { confirm: vi.fn(() => Promise.resolve('confirm')) },
    ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
  }
})

import AssistantHost from './AssistantHost.vue'

export const api = {
  cancelAiRun: vi.mocked(cancelAiRun),
  createAiSession: vi.mocked(createAiSession),
  deleteAiSession: vi.mocked(deleteAiSession),
  getAiRun: vi.mocked(getAiRun),
  getAiRunEvents: vi.mocked(getAiRunEvents),
  getAiSession: vi.mocked(getAiSession),
  getAiTools: vi.mocked(getAiTools),
  listAiSessions: vi.mocked(listAiSessions),
  sendAiMessage: vi.mocked(sendAiMessage),
  streamAiRunEvents: vi.mocked(streamAiRunEvents),
}

export const messageBox = { confirm: vi.mocked(ElMessageBox.confirm) }

export const router = { push: routerPush }

export function mockRouter(): { push: typeof routerPush } {
  return router
}

export function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  return { promise: new Promise<T>((done) => { resolve = done }), resolve }
}

export function mountAssistantHost(stubs: Record<string, unknown> = {}) {
  return mount(AssistantHost, {
    global: {
      stubs: {
        AssistantSettingsDialog: true,
        AssistantFloatBall: { emits: ['toggle'], template: '<button data-open @click="$emit(\'toggle\')" />' },
        ...stubs,
      },
    },
  })
}

export function resetAssistantHostMocks(): void {
  vi.useRealTimers()
  vi.clearAllMocks()
  messageBox.confirm.mockResolvedValue('confirm' as never)
}

export { AssistantHost, mount }

export function setupAfterEach(): void {
  afterEach(resetAssistantHostMocks)
}
