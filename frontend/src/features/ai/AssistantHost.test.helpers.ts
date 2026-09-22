import { mount } from '@vue/test-utils'
import { afterEach, vi } from 'vitest'
import { confirmDangerous } from '@/shared/lib/confirm'

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
import type {
  AiRun,
  AiSessionDetail,
  AiSessionSummary,
  AiToolsCatalog,
} from '@/shared/types/ai_assistant'

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

vi.mock('@/shared/lib/confirm', async (importOriginal) => ({ ...await importOriginal<typeof import('@/shared/lib/confirm')>(), confirmDangerous: vi.fn().mockResolvedValue(true) }))
vi.mock('vue-sonner', () => ({ toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() } }))

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

export const messageBox = { confirm: vi.mocked(confirmDangerous) }

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

// ---------------------------------------------------------------------------
// 共享 fixture：AssistantHost.*.test.ts 共用的报文与面板 stub。
// `vi.mock(...)` 是模块级提升的，只能待在本文件顶部（或各测试文件顶部）；
// 下面这些必须是纯数据/纯工厂，改契约时只改这一处。
// ---------------------------------------------------------------------------

/** 已配置模型、工具目录为空的 `GET /ai/tools`。 */
export function toolsReady(): AiToolsCatalog {
  return { provider_configured: true, tools: [] }
}

/** 会话详情报文；默认是刚新建、无消息的 `session-1`。 */
export function sessionDetail(overrides: Partial<AiSessionDetail> = {}): AiSessionDetail {
  return { id: 'session-1', title: '运行', status: 'idle', messages: [], ...overrides }
}

/** run 报文；默认是 `session-1` 上已收口的 `run-1`。 */
export function aiRun(overrides: Partial<AiRun> = {}): AiRun {
  return { id: 'run-1', session_id: 'session-1', status: 'done', ...overrides }
}

/** 干净起点：模型已配置 + 给定历史会话列表（默认无历史）。 */
export function primeAssistantReady(sessions: AiSessionSummary[] = []): void {
  api.getAiTools.mockResolvedValue(toolsReady())
  api.listAiSessions.mockResolvedValue(sessions)
}

/** 起点 + 首次发送即新建 `session-1`；发送与事件流仍由各用例自行编排。 */
export function primeNewSession(): void {
  primeAssistantReady()
  api.createAiSession.mockResolvedValue(sessionDetail())
}

/** 面板 stub 里的成绩单表达式：`内容:状态`，竖线拼接。 */
export const TRANSCRIPT_LINE =
  '{{ messages.map((message) => `${message.content}:${message.status}`).join("|") }}'

/** `角色:内容` 变体，用于校验轮次归属而非状态。 */
export const TRANSCRIPT_ROLE_LINE =
  '{{ messages.map((message) => `${message.role}:${message.content}`).join("|") }}'

export const CANCEL_BUTTON = '<button data-cancel @click="$emit(\'cancel\')" />'

/** 只发送、不看消息的最小面板。 */
export function sendPanel(text = '测试'): Record<string, unknown> {
  return {
    emits: ['send'],
    template: `<div data-panel><button data-send @click="$emit('send', '${text}')" /></div>`,
  }
}

/**
 * 成绩单面板：`[data-panel]` 内是 lead 文案 + 成绩单 + 发送（可选中止）按钮。
 * `props` 只写 messages 之外的额外 prop；`sendExpr` 用于发送内容依赖当前消息的用例。
 */
export function transcriptPanel(
  options: {
    props?: string[]
    lead?: string
    line?: string
    sendText?: string
    sendExpr?: string
    cancel?: boolean
  } = {},
): Record<string, unknown> {
  const payload = options.sendExpr ?? `'${options.sendText ?? '测试'}'`
  const cancel = options.cancel ? CANCEL_BUTTON : ''
  return {
    props: ['messages', ...(options.props ?? [])],
    emits: options.cancel ? ['send', 'cancel'] : ['send'],
    template:
      `<div data-panel>${options.lead ?? ''}${options.line ?? TRANSCRIPT_LINE}` +
      `<button data-send @click="$emit('send', ${payload})" />${cancel}</div>`,
  }
}
