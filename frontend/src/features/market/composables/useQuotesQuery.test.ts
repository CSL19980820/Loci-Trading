import { describe, expect, it } from 'vitest'

/**
 * Colada key 形状契约：改 key 会破坏缓存分区，需同步改 useQuotesQuery。
 * 此处不挂 Vue 应用，只钉死 key 拼装规则。
 */
function quotesQueryKey(
  code: string,
  opts: { adjust?: string; limit?: number; start?: string; end?: string } = {},
): readonly [string, string, string, number, string, string] {
  const c = code.trim()
  return [
    'market-quotes',
    c,
    opts.adjust ?? 'qfq',
    opts.limit ?? 800,
    opts.start ?? '',
    opts.end ?? '',
  ] as const
}

describe('useQuotesQuery key contract', () => {
  it('partitions by code and adjust', () => {
    expect(quotesQueryKey('600519', { adjust: 'qfq' })[1]).toBe('600519')
    expect(quotesQueryKey('600519', { adjust: 'hfq' })[2]).toBe('hfq')
    expect(quotesQueryKey('600519')[0]).toBe('market-quotes')
  })
})
