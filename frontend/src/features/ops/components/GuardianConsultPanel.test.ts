import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import GuardianConsultPanel from './GuardianConsultPanel.vue'
import { askGuardian, getGuardianConversation, getGuardianConversations } from '@/shared/api/guardian'

vi.mock('@/shared/api/guardian', () => ({ askGuardian: vi.fn(), getGuardianConversation: vi.fn(), getGuardianConversations: vi.fn() }))
beforeEach(() => {
  vi.resetAllMocks()
  // Real HTTP origins expose getRandomValues but not randomUUID.
  vi.stubGlobal('crypto', { getRandomValues: crypto.getRandomValues.bind(crypto) })
  vi.mocked(getGuardianConversations).mockResolvedValue({ conversations: [] })
  vi.mocked(askGuardian).mockImplementation(async p => ({ ...p, status: 'accepted' }))
  vi.mocked(getGuardianConversation).mockImplementation(async id => ({ id, title: '买贵了', notes: '实际100股', created: 1, updated: 2, turns: [{ id: 'r', question: '我买贵了怎么办', status: 'success', created: 1, result: { answer: '需要区分你的实际仓位和模拟持仓，先核对成本与日期。', model: 'deepseek-v4.1-flash' } }] }))
})
afterEach(() => vi.unstubAllGlobals())

it('sends real context separately and renders the consultation answer', async () => {
  const wrapper = mount(GuardianConsultPanel, { props: { model: 'deepseek-v4.1-flash' } })
  await flushPromises()
  const fields = wrapper.findAll('textarea')
  await fields[0]!.setValue('实际买入100股，成本12元')
  await fields[1]!.setValue('我买贵了怎么办')
  await wrapper.findAll('button').find(b => b.text() === '发送问题')!.trigger('click')
  await flushPromises()
  expect(askGuardian).toHaveBeenCalledWith(expect.objectContaining({ message: '我买贵了怎么办', real_context: '实际买入100股，成本12元' }))
  const payload = vi.mocked(askGuardian).mock.calls[0]![0]
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
  expect(payload.conversation_id).toMatch(uuid)
  expect(payload.request_id).toMatch(uuid)
  expect(payload.request_id).not.toBe(payload.conversation_id)
  expect(wrapper.find('.consult-answer').text()).toContain('先核对成本与日期')
  expect(wrapper.text()).toContain('咨询不执行交易')
  wrapper.unmount()
})

it('starts a distinct topic on HTTP and recovers after history loading fails', async () => {
  vi.mocked(getGuardianConversations).mockRejectedValueOnce(new Error('历史读取失败'))
  const wrapper = mount(GuardianConsultPanel, { props: { model: 'deepseek-v4.1-flash' } })
  await flushPromises()
  expect(wrapper.text()).toContain('历史读取失败')
  const send = async () => {
    await wrapper.findAll('textarea')[1]!.setValue('咨询链路测试')
    await wrapper.findAll('button').find(b => b.text() === '发送问题')!.trigger('click')
    await flushPromises()
  }
  await send()
  const first = vi.mocked(askGuardian).mock.calls[0]![0]
  await wrapper.findAll('button').find(b => b.text() === '新话题')!.trigger('click')
  expect(wrapper.findAll('.consult-turn')).toHaveLength(0)
  expect(wrapper.text()).not.toContain('历史读取失败')
  await send()
  const second = vi.mocked(askGuardian).mock.calls[1]![0]
  expect(second.conversation_id).not.toBe(first.conversation_id)
  expect(second.request_id).not.toBe(first.request_id)
  wrapper.unmount()
})

it('reuses the request id after a network error to avoid duplicate paid questions', async () => {
  vi.mocked(askGuardian).mockRejectedValueOnce(new Error('网络断开'))
  const wrapper = mount(GuardianConsultPanel, { props: { model: 'deepseek-v4.1-flash' } })
  await flushPromises()
  await wrapper.findAll('textarea')[1]!.setValue('我买贵了怎么办')
  const send = () => wrapper.findAll('button').find(b => b.text() === '发送问题')!.trigger('click')
  await send(); await flushPromises()
  expect(wrapper.text()).toContain('网络断开')
  const first = vi.mocked(askGuardian).mock.calls[0]![0].request_id
  await send(); await flushPromises()
  expect(vi.mocked(askGuardian).mock.calls[1]![0].request_id).toBe(first)
  wrapper.unmount()
})
