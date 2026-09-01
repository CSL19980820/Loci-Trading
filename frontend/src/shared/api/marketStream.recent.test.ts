import { describe, expect, it, vi, beforeEach } from 'vitest'

/*
 * 信号历史接口的解析契约。后端字段是 snake_case，且早期契约 items / signals
 * 两种键名都出现过——解析错的表现是「接口 200、界面一条不显示」，最难查，
 * 所以在这里钉死。
 */

const client = vi.hoisted(() => ({
  quantRequest: vi.fn(),
  query: (params: Record<string, string | number | undefined>) => {
    const search = new URLSearchParams()
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== '') search.set(key, String(value))
    }
    const text = search.toString()
    return text ? `?${text}` : ''
  },
}))

vi.mock('@/shared/api/quant_client', () => client)

import { getRecentSignals } from './marketStream'

beforeEach(() => {
  client.quantRequest.mockReset()
})

describe('getRecentSignals', () => {
  it('按 limit 拼路径并解析 snake_case 字段', async () => {
    client.quantRequest.mockResolvedValue({
      as_of: '2026-08-28T15:00:00',
      items: [
        {
          id: 'sig_1',
          code: '600519',
          name: '贵州茅台',
          rule: 'ma_golden_cross',
          rule_label: '均线金叉',
          detail: 'MA5 上穿 MA20',
          direction: 'long',
          strength: 66,
          price: 1800,
          pct: 1.2,
          provisional: false,
          triggered_at: '2026-08-28T14:59:00',
        },
      ],
    })

    const result = await getRecentSignals(80)

    expect(client.quantRequest).toHaveBeenCalledWith('/market/signals/recent?limit=80')
    expect(result.asOf).toBe('2026-08-28T15:00:00')
    expect(result.items).toHaveLength(1)
    expect(result.items[0]?.strategy).toBe('ma_golden_cross')
    expect(result.items[0]?.strategyName).toBe('均线金叉')
    expect(result.items[0]?.triggeredAt).toBe('2026-08-28T14:59:00')
  })

  it('后端用 signals 键时同样认', async () => {
    client.quantRequest.mockResolvedValue({
      as_of: '',
      signals: [{ id: 'sig_2', code: '000001', rule: 'fast_surge' }],
    })

    const result = await getRecentSignals()

    expect(result.items.map((row) => row.id)).toEqual(['sig_2'])
  })

  it('空体/异常体不炸，返回空列表', async () => {
    client.quantRequest.mockResolvedValue(null)

    const result = await getRecentSignals()

    expect(result.items).toEqual([])
    expect(result.asOf).toBe('')
  })
})
