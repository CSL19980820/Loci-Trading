import { describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  getDataLocation: vi.fn(),
  getDesktopPrefs: vi.fn(),
  getMarketSyncSettings: vi.fn(),
  getMcpServers: vi.fn(),
  getProviders: vi.fn(),
  getWecomSettings: vi.fn(),
}))

vi.mock('@/shared/api/quant', () => api)
vi.mock('@/shared/lib/theme', () => ({
  APPEARANCE_OPTIONS: [{ id: 'system', label: '跟随系统' }],
  getStoredAppearance: () => 'system',
}))

import { useSettingsSummaries } from './useSettingsSummaries'

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

describe('useSettingsSummaries request ordering', () => {
  it('does not let an older summary refresh replace a newer one', async () => {
    const oldMcp = deferred<{ is_active: boolean }[]>()
    const newMcp = deferred<{ is_active: boolean }[]>()
    api.getMcpServers.mockImplementationOnce(() => oldMcp.promise).mockImplementationOnce(() => newMcp.promise)
    api.getProviders.mockResolvedValue([])
    api.getDataLocation.mockResolvedValue(null)
    api.getMarketSyncSettings.mockResolvedValue(null)
    api.getWecomSettings.mockResolvedValue(null)
    api.getDesktopPrefs.mockResolvedValue(null)
    const summaries = useSettingsSummaries()

    const first = summaries.refresh()
    const second = summaries.refresh()
    newMcp.resolve([])
    await second
    oldMcp.resolve([{ is_active: true }])
    await first

    expect(summaries.summaries.mcp).toEqual({ tail: '未配', state: 'idle' })
  })
})
