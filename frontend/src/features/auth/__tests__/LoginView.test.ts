import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import LoginView from '@/features/ledger/LoginView.vue'
import * as authApi from '@/shared/api/auth'
import type { AuthOptionsResponse } from '@/shared/types/auth'

const mockPush = vi.fn()
const mockReplace = vi.fn()

vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: mockPush,
    replace: mockReplace,
  }),
  useRoute: () => ({
    query: {},
    fullPath: '/login',
  }),
}))

vi.mock('@/shared/api/auth', () => ({
  getAuthOptions: vi.fn(),
  loginWithPassword: vi.fn(),
  registerWithEmail: vi.fn(),
  verifyEmail: vi.fn(),
  requestForgotPassword: vi.fn(),
  resendVerificationCode: vi.fn(),
  resetPassword: vi.fn(),
  claimQrSession: vi.fn(),
}))

describe('LoginView.vue', () => {
  const optionsRes: AuthOptionsResponse = {
    email_signup: true,
    providers: [
      { name: 'mock', family: 'mock', label: '演示扫码', mode: 'qrcode' },
    ],
  }

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked(authApi.getAuthOptions).mockResolvedValue(optionsRes)
  })

  it('renders login options and only shows enabled providers', async () => {
    const wrapper = mount(LoginView, {
      global: {
        stubs: {
          'el-input': { template: '<input />' },
          'el-button': { template: '<button><slot /></button>' },
          'el-form': { template: '<form><slot /></form>' },
          'el-form-item': { template: '<div><slot /></div>' },
          'el-alert': { template: '<div><slot /></div>' },
          'el-divider': { template: '<hr />' },
          'el-icon': { template: '<span><slot /></span>' },
        },
      },
    })

    await flushPromises()

    expect(authApi.getAuthOptions).toHaveBeenCalled()
    // Should render mock provider button but no others
    expect(wrapper.text()).toContain('演示扫码')
    expect(wrapper.text()).not.toContain('微信')
    expect(wrapper.text()).not.toContain('QQ')
  })
})
