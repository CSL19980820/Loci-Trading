import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { LanesCatalog } from '@/shared/types/quant'

const api = vi.hoisted(() => ({
  fetchLanesCatalog: vi.fn(),
  getAkshareSources: vi.fn(),
  patchLaneProvider: vi.fn(),
  probeLanes: vi.fn(),
  saveLanePolicy: vi.fn(),
  speedtestLane: vi.fn(),
}))

vi.mock('@/shared/api/quant', () => api)

import { useDataSources } from './useDataSources'

const CATALOG: LanesCatalog = {
  lanes: [
    { id: 'hist_daily', label: '历史日 K', required: true },
    { id: 'minute_bars', label: '分钟 K', required: false },
  ],
  providers: [
    {
      id: 'sina',
      label: '新浪直连',
      lanes: ['hist_daily'],
      enabled: true,
      disabled_lanes: [],
    },
    {
      id: 'eastmoney',
      label: '东财',
      lanes: ['hist_daily', 'minute_bars'],
      enabled: true,
      disabled_lanes: ['minute_bars'],
    },
    {
      id: 'tencent',
      label: '腾讯财经',
      lanes: ['hist_daily'],
      enabled: false,
      disabled_lanes: [],
    },
  ],
  policies: [
    {
      lane: 'hist_daily',
      mode: 'auto',
      fallback: false,
      effective_provider_ids: ['sina', 'eastmoney'],
    },
    { lane: 'minute_bars', mode: 'auto', fallback: false, effective_provider_ids: [] },
  ],
}

function withCatalog(catalog: LanesCatalog = CATALOG) {
  api.fetchLanesCatalog.mockResolvedValue(structuredClone(catalog))
  api.getAkshareSources.mockResolvedValue({ sources: [{ id: 'sina', count: 12 }] })
  return useDataSources()
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

describe('useDataSources', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('counts data sources only, never their tools', async () => {
    const store = withCatalog()
    await store.load()

    expect(store.stats.value).toEqual({ total: 3, enabled: 2, disabled: 1 })
  })

  it('reads a tool as disabled when the source is off or that single lane is muted', async () => {
    const store = withCatalog()
    await store.load()

    const eastmoney = store.sources.value.find((row) => row.id === 'eastmoney')!
    expect(eastmoney.enabled).toBe(true)
    expect(eastmoney.enabledCount).toBe(1)
    expect(eastmoney.disabledCount).toBe(1)
    expect(eastmoney.interfaceCount).toBeUndefined()

    const sina = store.sources.value.find((row) => row.id === 'sina')!
    expect(sina.interfaceCount).toBe(12)
    expect(sina.tools[0]?.order).toBe(1)

    // 源总开关关掉 → 它的工具一个都不算启用
    const tencent = store.sources.value.find((row) => row.id === 'tencent')!
    expect(tencent.enabledCount).toBe(0)
    expect(tencent.disabledCount).toBe(1)
  })

  it('lists akshare-only upstreams as data sources too', async () => {
    api.fetchLanesCatalog.mockResolvedValue(structuredClone(CATALOG))
    api.getAkshareSources.mockResolvedValue({
      sources: [
        { id: 'sina', count: 12 },
        { id: 'tonghuashun', count: 40 },
        { id: 'xueqiu', count: 6 },
      ],
    })
    const store = useDataSources()
    await store.load()

    const ths = store.sources.value.find((row) => row.id === 'tonghuashun')!
    expect(ths.label).toBe('同花顺')
    expect(ths.interfaceOnly).toBe(true)
    expect(ths.tools).toEqual([])
    // 接口源一律视为可用面（无上桌开关）
    expect(ths.enabled).toBe(true)
    expect(store.sources.value.find((row) => row.id === 'xueqiu')!.enabled).toBe(true)
    expect(store.sources.value.find((row) => row.id === 'sina')!.interfaceCount).toBe(12)
    expect(store.stats.value).toEqual({ total: 5, enabled: 4, disabled: 1 })
  })

  it('flags a required lane that has no source left', async () => {
    const store = withCatalog({
      ...CATALOG,
      policies: [
        { lane: 'hist_daily', mode: 'auto', fallback: false, effective_provider_ids: [] },
        { lane: 'minute_bars', mode: 'auto', fallback: false, effective_provider_ids: [] },
      ],
    })
    await store.load()

    expect(store.brokenRequiredLanes.value.map((row) => row.label)).toEqual(['历史日 K'])
  })

  it('passes the lane through when a single tool is toggled', async () => {
    const store = withCatalog()
    await store.load()
    api.patchLaneProvider.mockResolvedValue({ id: 'eastmoney', label: '东财', enabled: true })

    await store.toggleTool('eastmoney', 'minute_bars', true)

    expect(api.patchLaneProvider).toHaveBeenCalledWith('eastmoney', true, 'minute_bars')
    // 源总开关走同一个接口，但不带 lane
    await store.toggleSource('eastmoney', false)
    expect(api.patchLaneProvider).toHaveBeenLastCalledWith('eastmoney', false)
  })

  it('switches the whole source back on when a lane of a stopped source is enabled', async () => {
    const store = withCatalog()
    await store.load()
    api.patchLaneProvider.mockResolvedValue({ id: 'tencent', label: '腾讯财经', enabled: true })

    const laneRow = store.laneRows.value.find((row) => row.lane === 'hist_daily')!
    expect(laneRow.sources.find((item) => item.id === 'tencent')?.masterOff).toBe(true)

    await store.toggleTool('tencent', 'hist_daily', true)

    expect(api.patchLaneProvider).toHaveBeenNthCalledWith(1, 'tencent', true)
    expect(api.patchLaneProvider).toHaveBeenNthCalledWith(2, 'tencent', true, 'hist_daily')
    expect(store.notice.value).toContain('整源启用')
  })

  it('does not touch the master switch when a lane is muted', async () => {
    const store = withCatalog()
    await store.load()
    api.patchLaneProvider.mockResolvedValue({ id: 'sina', label: '新浪直连', enabled: true })

    await store.toggleTool('sina', 'hist_daily', false)

    expect(api.patchLaneProvider).toHaveBeenCalledTimes(1)
    expect(api.patchLaneProvider).toHaveBeenCalledWith('sina', false, 'hist_daily')
  })

  it('files probe rows under source × tool and takes the median of the good ones', async () => {
    const store = withCatalog()
    await store.load()
    api.probeLanes.mockResolvedValue({
      results: [
        { adapter_id: 'eastmoney', lane: 'hist_daily', ok: true, rtt_ms: 120, rows: 5 },
        { adapter_id: 'eastmoney', lane: 'minute_bars', ok: false, rtt_ms: 900, error: '超时' },
      ],
    })

    await store.probeSource('eastmoney')

    expect(api.probeLanes).toHaveBeenCalledWith(null, 'eastmoney', { code: '600519', runs: 1 })
    const eastmoney = store.sources.value.find((row) => row.id === 'eastmoney')!
    expect(eastmoney.medianRttMs).toBe(120)
    expect(eastmoney.failedCount).toBe(1)
    expect(eastmoney.tools.find((tool) => tool.lane === 'minute_bars')?.probe?.error).toBe('超时')
  })

  it('refuses to probe with a code that is not six digits', async () => {
    const store = withCatalog()
    await store.load()
    store.code.value = '12'

    await store.probeAll()

    expect(api.probeLanes).not.toHaveBeenCalled()
    expect(store.error.value).toContain('6 位数字')
  })

  it('keeps the download test result marked as a download reading', async () => {
    const store = withCatalog()
    await store.load()
    api.speedtestLane.mockResolvedValue({
      lane: 'hist_daily',
      results: [{ adapter_id: 'sina', code: '600519', ok: true, elapsed_ms: 640, rows: 1200 }],
    })

    await store.downloadTest('hist_daily')

    const cell = store.cells.value['sina:hist_daily']
    expect(cell).toMatchObject({ kind: 'download', rttMs: 640, rows: 1200, ok: true })
  })

  it('does not write a catalog response after its owning panel unmounts', async () => {
    const catalog = deferred<LanesCatalog>()
    api.fetchLanesCatalog.mockReturnValue(catalog.promise)
    api.getAkshareSources.mockResolvedValue({ sources: [] })

    let store!: ReturnType<typeof useDataSources>
    const Probe = defineComponent({
      setup() {
        store = useDataSources()
        return () => h('div')
      },
    })
    const wrapper = mount(Probe)

    const load = store.load()
    wrapper.unmount()
    catalog.resolve(structuredClone(CATALOG))
    await load
    await flushPromises()

    expect(store.providers.value).toEqual([])
    expect(store.loading.value).toBe(true)
  })
})
