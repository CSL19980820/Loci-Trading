import { beforeEach, describe, expect, it, vi } from 'vitest'

/*
 * 规则接口的路径与解析契约。
 *
 * 后端实现的是 /api/market/signals/rules（GET 回 { rules: [...] }，元素用
 * rule_id / min_bars / param_specs），最初的联调契约写的是 /market/signal-rules
 * 且直接回数组。两套都要能跑通——对不上的症状是设置页整块 404。
 */

const client = vi.hoisted(() => ({ quantRequest: vi.fn(), query: () => '' }))

vi.mock('@/shared/api/quant_client', () => client)

import { getSignalRules, updateSignalRule } from './signalRules'

function notFound(): Error & { status: number } {
  return Object.assign(new Error('Not Found'), { status: 404 })
}

const backendRule = {
  rule_id: 'ma_golden_cross',
  label: '均线金叉',
  description: '快线上穿慢线',
  enabled: true,
  params: { fast: 5, slow: 20 },
  defaults: { fast: 5, slow: 20 },
  overrides: {},
  min_bars: 21,
  repeatable: false,
  param_specs: [
    { key: 'fast', label: '快线', default: 5, min: 2, max: 60, unit: '日', integer: true },
  ],
}

beforeEach(() => {
  client.quantRequest.mockReset()
})

describe('getSignalRules', () => {
  it('读 /market/signals/rules 并解析 rule_id / min_bars / param_specs', async () => {
    client.quantRequest.mockResolvedValue({ count: 1, rules: [backendRule] })

    const rules = await getSignalRules()

    expect(client.quantRequest).toHaveBeenCalledWith('/market/signals/rules')
    expect(rules).toHaveLength(1)
    expect(rules[0]?.id).toBe('ma_golden_cross')
    expect(rules[0]?.minBars).toBe(21)
    expect(rules[0]?.params).toEqual({ fast: 5, slow: 20 })
    expect(rules[0]?.specs[0]?.integer).toBe(true)
  })

  it('404 不再偷偷试第二条路径：路径已与后端对齐，回退分支已删', async () => {
    client.quantRequest.mockRejectedValue(notFound())

    await expect(getSignalRules()).rejects.toBeTruthy()
    expect(client.quantRequest).toHaveBeenCalledTimes(1)
expect(client.quantRequest).toHaveBeenCalledWith('/market/signals/rules')
  })

  it('404 以外的错误直接上抛，不静默吞掉', async () => {
    client.quantRequest.mockRejectedValue(Object.assign(new Error('库忙'), { status: 503 }))

    await expect(getSignalRules()).rejects.toThrow('库忙')
    expect(client.quantRequest).toHaveBeenCalledTimes(1)
  })
})

describe('updateSignalRule', () => {
  it('PUT 到规则路径，body 只带改动字段', async () => {
    client.quantRequest.mockResolvedValue(backendRule)

    const saved = await updateSignalRule('ma_golden_cross', { params: { fast: 8, slow: 20 } })

    expect(client.quantRequest).toHaveBeenCalledWith('/market/signals/rules/ma_golden_cross', {
      method: 'PUT',
      body: JSON.stringify({ params: { fast: 8, slow: 20 } }),
    })
    expect(saved?.id).toBe('ma_golden_cross')
  })

  it('后端不回规则体时返回 null，界面保留乐观值', async () => {
    client.quantRequest.mockResolvedValue(null)

    await expect(updateSignalRule('fast_surge', { enabled: false })).resolves.toBeNull()
  })
})
