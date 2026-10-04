import { afterEach, describe, expect, it, vi } from 'vitest'
import { getScreenRunStatus } from './quant_strategy'

afterEach(() => { vi.unstubAllGlobals() })

describe('screen run progress projection API', () => {
  it('preserves the default full route and encodes progress and individual strategy options', async () => {
    const fetcher = vi.fn(async (_url: string) => new Response('{}'))
    vi.stubGlobal('fetch', fetcher)
    await getScreenRunStatus()
    await getScreenRunStatus({ view: 'progress' })
    await getScreenRunStatus({ strategy: 'fixture strategy/one' })
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      '/api/screen/run', '/api/screen/run?view=progress', '/api/screen/run?strategy=fixture+strategy%2Fone',
    ])
  })
})
