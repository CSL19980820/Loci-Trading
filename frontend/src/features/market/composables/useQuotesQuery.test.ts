import { PiniaColada } from '@pinia/colada'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { defineComponent, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getQuotes } from '@/shared/api/quant_market'

import { useQuotesQuery } from './useQuotesQuery'

vi.mock('@/shared/api/quant_market', () => ({
  getQuotes: vi.fn(),
}))

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
    opts.limit ?? 60,
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

describe('useQuotesQuery failure state', () => {
  beforeEach(() => {
    vi.mocked(getQuotes).mockReset()
  })

  it('exposes a failure separately from an empty quote result', async () => {
    vi.mocked(getQuotes).mockRejectedValue(new Error('行情服务不可用'))
    const Probe = defineComponent({
      setup() {
        return useQuotesQuery(ref('600519'))
      },
      template: '<span>{{ isError ? error?.message : quote ? "quote" : "empty" }}</span>',
    })

    const wrapper = mount(Probe, {
      global: { plugins: [createPinia(), PiniaColada] },
    })
    await flushPromises()

    expect(wrapper.text()).toBe('行情服务不可用')
  })
})
