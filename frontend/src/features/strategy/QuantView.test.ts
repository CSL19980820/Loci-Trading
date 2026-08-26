import { mount } from '@vue/test-utils'
import { nextTick, reactive } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  getJobs: vi.fn(),
  getMarketCoverage: vi.fn(),
  getSkills: vi.fn(),
  getStrategies: vi.fn(),
  removeSkill: vi.fn(),
  syncMarket: vi.fn(),
}))

const route = reactive({ query: { tab: 'research' as string | undefined } })
const router = { push: vi.fn(), replace: vi.fn() }

vi.mock('vue-router', () => ({
  useRoute: () => route,
  useRouter: () => router,
}))

vi.mock('@/shared/api/quant', () => ({
  ...api,
  CapabilityUnavailableError: class CapabilityUnavailableError extends Error {},
}))

import QuantView from './QuantView.vue'

const BusyStub = {
  props: { busy: Boolean },
  template: '<div v-if="busy" data-testid="page-busy" />',
}

function pendingRequests(): void {
  const pending = new Promise<never>(() => {})
  api.getStrategies.mockReturnValue(pending)
  api.getSkills.mockReturnValue(pending)
  api.getMarketCoverage.mockReturnValue(pending)
  api.getJobs.mockReturnValue(pending)
}

function mountView() {
  return mount(QuantView, {
    shallow: true,
    global: { stubs: { PageBusy: BusyStub } },
  })
}

describe('QuantView', () => {
  afterEach(() => {
    route.query.tab = 'research'
    vi.clearAllMocks()
  })

  it('keeps the research tab usable while unrelated workshop summaries are loading', async () => {
    pendingRequests()
    const wrapper = mountView()
    await nextTick()

    expect(wrapper.find('[data-testid="page-busy"]').exists()).toBe(false)

    route.query.tab = 'engines'
    await nextTick()

    expect(wrapper.find('[data-testid="page-busy"]').exists()).toBe(true)
    wrapper.unmount()
  })
})
