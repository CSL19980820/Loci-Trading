import { describe, expect, it } from 'vitest'
import { describeSession, blockHint, phaseLabel } from '../lib/sessionCopy'

/*
 * 这组用例守的是一句用户原话:「动不动就是连接中断」。
 *
 * 真相是上游东财全市场截面挂了(生产日志每分钟数条 `实时推流 feed all 取数失败`),
 * 而 SSE 链路完好、心跳照发。文案必须把**链路**和**数据源**分开说,
 * 否则就是拿链路去背数据源的锅,用户照着错误的方向排查。
 */
describe('describeSession 链路与数据源分开报', () => {
  it('链路好但数据没喂上来:说数据源,不许说连接', () => {
    const d = describeSession('connected', true, 'morning', true)
    expect(d.text).toBe('数据源暂无更新·链路正常')
  expect(d.tone).toBe('warn')
    // 不许出现「连接」「断」这类把锅甩给链路的字
    expect(d.text).not.toMatch(/连接中断|已断开|重连/)
  })

  it('链路好且数据在走:实时推流中', () => {
    const d = describeSession('connected', true, 'morning', false)
    expect(d.text).toBe('实时推流中')
    expect(d.tone).toBe('live')
  })

  it('真断线仍然照实说', () => {
    expect(describeSession('offline', true, 'morning', false).text).toBe('连接已断开·自动重连中')
  expect(describeSession('reconnecting', true, 'morning', false).text).toBe(
      '重连中·恢复后自动续推',
    )
  })

  it('非交易时段:数据不动是正常的,dataStale 也不该改口', () => {
    const d = describeSession('connected', false, 'closed', true)
    expect(d.text).toBe('已收盘·展示最近快照')
    expect(d.tone).toBe('idle')
  })

  it('dataStale 默认 false:老调用方不传也不会改变行为', () => {
    expect(describeSession('connected', true, 'morning').text).toBe('实时推流中')
  })
})

describe('sessionCopy 其余约定', () => {
  it('blockHint 只给短语,不解释会话状态', () => {
    expect(blockHint('offline', '暂无数据')).toBe('连接中断')
    expect(blockHint('connected', '暂无数据')).toBe('暂无数据')
// ≤8 字:子块不许出现长句
    expect(blockHint('offline', '暂无数据').length).toBeLessThanOrEqual(8)
  })

  it('未知 phase 原样带出,不编造中文', () => {
    expect(phaseLabel('morning')).toBe('早盘交易')
    expect(phaseLabel('weird_phase')).toBe('weird_phase')
    expect(phaseLabel('')).toBe('非交易时段')
  })
})
