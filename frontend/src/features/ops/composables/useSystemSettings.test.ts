import { describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  getDataLocation: vi.fn(),
  getMarketSyncSettings: vi.fn(),
  getWecomSettings: vi.fn(),
  saveDataLocation: vi.fn(),
  saveMarketSyncSettings: vi.fn(),
  saveWecomSettings: vi.fn(),
  testWecomSettings: vi.fn(),
}))

vi.mock('@/shared/api/quant', () => api)

import { useSystemSettings } from './useSystemSettings'

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function dataLocation(dataDir: string) {
  return {
    data_dir: dataDir,
    pending_data_dir: '',
    default_dir: 'D:/default',
    restart_required: false,
  }
}

describe('useSystemSettings request ordering', () => {
  it('does not let an older settings load replace a newer draft', async () => {
    const oldLocation = deferred<ReturnType<typeof dataLocation>>()
    const newLocation = deferred<ReturnType<typeof dataLocation>>()
    api.getDataLocation.mockImplementationOnce(() => oldLocation.promise).mockImplementationOnce(() => newLocation.promise)
    api.getMarketSyncSettings.mockResolvedValue({
      enabled_intraday: false,
      interval_minutes: 5,
      enabled_eod: false,
      eod_hour: 16,
      eod_minute: 0,
      workers: 4,
      push_wecom_on_fail: false,
      intraday_job: null,
      eod_job: null,
    })
    api.getWecomSettings.mockResolvedValue({ configured: false, url_masked: '' })
    const settings = useSystemSettings()

    const first = settings.load()
    const second = settings.load()
    newLocation.resolve(dataLocation('D:/new'))
    await second
    oldLocation.resolve(dataLocation('D:/old'))
    await first

    expect(settings.locationDir.value).toBe('D:/new')
  })
})
