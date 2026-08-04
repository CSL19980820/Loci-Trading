import { flushPromises, mount } from '@vue/test-utils'
import { computed, ref } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ArchiveView from './ArchiveView.vue'

const quoteError = ref<Error | null>(null)
const ledgerError = ref('')

vi.mock('@/features/market/composables/useQuotesQuery', () => ({
  useQuotesQuery: () => ({
    quote: ref(null),
    refetch: vi.fn(),
    isPending: ref(false),
    isLoading: ref(false),
    error: quoteError,
    isError: computed(() => quoteError.value !== null),
  }),
}))

vi.mock('@/shared/stores/palace', () => ({
  usePalaceStore: () => ({
    loading: false,
    error: ledgerError,
    selectedCode: '',
    selectedTimeline: [],
    trades: [],
    dashboard: null,
  }),
}))

vi.mock('@/shared/stores/batchBrowse', () => ({
  useBatchBrowseStore: () => ({
    active: false,
    index: -1,
    total: 0,
    dockOpen: false,
    session: null,
    items: [],
    syncCode: vi.fn(),
    step: vi.fn(),
    goTo: vi.fn(),
    toggleDock: vi.fn(),
  }),
}))

function mountArchive(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/archive/:code', component: ArchiveView }],
  })
  return router.push(path).then(async () => {
    await router.isReady()
    return mount(ArchiveView, {
      global: {
        plugins: [router],
        stubs: {
          ArchiveBatchDock: true,
          ArchiveBatchRail: true,
          DataQueryDetailPanel: { template: '<div>行情面板</div>' },
          EmptyState: { template: '<div><slot /></div>' },
          PageBusy: true,
          Sheet: { template: '<section><slot /></section>' },
          StockTimeline: true,
          TradesTable: true,
          'el-alert': { props: ['title'], template: '<div role="alert">{{ title }}<slot /></div>' },
          'el-button': { template: '<button><slot /></button>' },
          'el-tag': { template: '<span><slot /></span>' },
        },
      },
    })
  })
}

describe('ArchiveView failure states', () => {
  beforeEach(() => {
    quoteError.value = null
    ledgerError.value = ''
    vi.stubGlobal('matchMedia', () => ({ matches: false }))
  })

  it('shows a quote failure instead of the empty market state', async () => {
    quoteError.value = new Error('行情服务不可用')
    const wrapper = await mountArchive('/archive/600519')
    await flushPromises()

    expect(wrapper.text()).toContain('行情服务不可用')
    expect(wrapper.text()).not.toContain('该证券暂无本机日线')
  })

  it('shows a ledger failure instead of empty trade records', async () => {
    ledgerError.value = '成交加载失败'
    const wrapper = await mountArchive('/archive/600519?view=trades')
    await flushPromises()

    expect(wrapper.text()).toContain('成交加载失败')
    expect(wrapper.text()).not.toContain('尚无交割记录')
  })
})
