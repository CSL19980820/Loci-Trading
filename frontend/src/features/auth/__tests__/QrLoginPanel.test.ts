import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'

import QrLoginPanel from '@/features/auth/QrLoginPanel.vue'
import * as authApi from '@/shared/api/auth'
import type { ProviderOption, QrPollResult, QrStartResult } from '@/shared/types/auth'

vi.mock('@/shared/api/auth', () => ({
  startQrLogin: vi.fn(),
  pollQrState: vi.fn(),
  claimQrSession: vi.fn(),
  markQrScanned: vi.fn(),
  confirmMockQr: vi.fn(),
}))

describe('QrLoginPanel.vue', () => {
  const mockProvider: ProviderOption = {
    name: 'mock',
    family: 'mock',
    label: '演示扫码',
    mode: 'qrcode',
  }

  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
  })

  it('initializes QR flow, starts polling, and handles state transitions', async () => {
    const startRes: QrStartResult = {
      state: 'st_12345678',
      mode: 'qrcode',
      qr_content: 'mock-qr-content',
      expires_in: 300,
    }
    vi.mocked(authApi.startQrLogin).mockResolvedValue(startRes)

    const pollResPending: QrPollResult = { status: 'pending' }
    const pollResScanned: QrPollResult = { status: 'scanned' }
    const pollResConfirmed: QrPollResult = { status: 'confirmed' }

    vi.mocked(authApi.pollQrState)
      .mockResolvedValueOnce(pollResPending)
      .mockResolvedValueOnce(pollResScanned)
      .mockResolvedValueOnce(pollResConfirmed)

    vi.mocked(authApi.claimQrSession).mockResolvedValue({
      authenticated: true,
      user: {
        id: 'u_1',
        username: 'demo_user',
        display_name: 'Demo',
        avatar_url: '',
        bio: '',
        role: 'member',
        created_at: '',
      },
    })

    const wrapper = mount(QrLoginPanel, {
      props: {
        provider: mockProvider,
        redirectTo: '/dashboard',
      },
      global: {
        stubs: {
          'el-icon': true,
          'el-divider': true,
          'el-button': true,
        },
      },
    })

    await flushPromises()

    expect(authApi.startQrLogin).toHaveBeenCalledWith({
      provider: 'mock',
      redirect_to: '/dashboard',
    })

    // Advance 2 seconds for first poll
    await vi.advanceTimersByTimeAsync(2000)
    expect(authApi.pollQrState).toHaveBeenCalledTimes(1)
    expect(authApi.pollQrState).toHaveBeenCalledWith('st_12345678')

    // Advance 2 seconds for second poll (scanned)
    await vi.advanceTimersByTimeAsync(2000)
    expect(authApi.pollQrState).toHaveBeenCalledTimes(2)

    // Advance 2 seconds for third poll (confirmed -> auto claim)
    await vi.advanceTimersByTimeAsync(2000)
    expect(authApi.pollQrState).toHaveBeenCalledTimes(3)
    expect(authApi.claimQrSession).toHaveBeenCalledWith('st_12345678')

    await flushPromises()

    expect(wrapper.emitted('success')).toBeTruthy()
    expect(wrapper.emitted('success')![0][0]).toMatchObject({ username: 'demo_user' })
  })

  it('cleans up timers when component is unmounted', async () => {
    const startRes: QrStartResult = {
      state: 'st_12345678',
      mode: 'qrcode',
      qr_content: 'mock-qr-content',
      expires_in: 300,
    }
    vi.mocked(authApi.startQrLogin).mockResolvedValue(startRes)
    vi.mocked(authApi.pollQrState).mockResolvedValue({ status: 'pending' })

    const wrapper = mount(QrLoginPanel, {
      props: {
        provider: mockProvider,
      },
      global: {
        stubs: {
          'el-icon': true,
          'el-divider': true,
          'el-button': true,
        },
      },
    })

    await flushPromises()

    // 此时已经启动了轮询定时器，我们在下一次 tick 前卸载
    wrapper.unmount()

    // 卸载后等待 10s，由于 timer 已在 unmount 中 clear，因此 pollQrState 不应被调用
    await vi.advanceTimersByTimeAsync(10000)
    expect(authApi.pollQrState).not.toHaveBeenCalled()
  })
})
