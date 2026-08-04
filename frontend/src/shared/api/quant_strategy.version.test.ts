import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  deleteStrategyVersion,
  getStrategyVersions,
  rollbackStrategyVersion,
} from './quant_strategy'

describe('strategy version API', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('uses the unified backend rollback route and string versions', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([])))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        slug: 'my/strategy', version: '7', file: 'strategy/custom/my.py', registered: true,
      })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ removed: true })))
    vi.stubGlobal('fetch', fetchMock)

    await getStrategyVersions('my/strategy')
    await rollbackStrategyVersion('my/strategy', '7')
    await deleteStrategyVersion('my/strategy', '7')

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/strategies/my%2Fstrategy/versions',
      expect.objectContaining({ credentials: 'same-origin' }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/strategies/my%2Fstrategy/rollback',
      expect.objectContaining({
        method: 'POST',
        credentials: 'same-origin',
        body: JSON.stringify({ version: '7' }),
      }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      '/api/strategies/my%2Fstrategy/versions/7',
      expect.objectContaining({ method: 'DELETE', credentials: 'same-origin' }),
    )
  })
})
