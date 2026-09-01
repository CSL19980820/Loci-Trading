import { describe, expect, it } from 'vitest'

import { dialogWidth, strategyLabel, strategyShortLabel } from './format'

describe('dialogWidth', () => {
  it('uses a CSS-constrained width that stays responsive after a dialog opens', () => {
    expect(dialogWidth()).toBe('min(52rem, 94vw)')
  })
})

/*
 * 界面上不许露出英文 slug（用户已反复提过）。这里钉住三件事：
 *   1 现役战法的精确名
 *   2 表外的新版本号 / 新变体也要落到中文（靠拼音词根兜底）
 *   3 窄位短名去掉括注，但保留「已下线」状态
 */
describe('strategyLabel', () => {
  it('maps the three live builtin slugs to Chinese', () => {
    expect(strategyLabel('sanyuan-tail-v1')).toBe('三源尾盘共振（15:30）')
    expect(strategyLabel('qianlong-close-v3')).toBe('潜龙出海（V3.2）')
    expect(strategyLabel('yangshi-tail-v1')).toBe('杨氏尾盘选股（15:30）')
  })

  it('falls back through pinyin stems so unseen versions never leak English', () => {
    for (const slug of [
      'sanyuan-tail-v4',
      'SANYUAN_TAIL_2027',
      'qianlong-close-v9',
      'yangshi-tail-v2',
      'lugw-sanwai-v2',
    ]) {
      expect(strategyLabel(slug), slug).toMatch(/^[^\u0000-\u007F]/)
    }
  })

  it('keeps Chinese custom names and honours a caller-supplied map', () => {
    expect(strategyLabel('我的自定义战法')).toBe('我的自定义战法')
    expect(strategyLabel('abc-v1', new Map([['abc-v1', '甲乙丙']]))).toBe('甲乙丙')
  })

  it('returns an em dash for empty input', () => {
    expect(strategyLabel('')).toBe('—')
    expect(strategyLabel(null)).toBe('—')
  expect(strategyLabel(undefined)).toBe('—')
  })
})

describe('strategyShortLabel', () => {
  it('drops timing / version parentheticals for narrow columns', () => {
    expect(strategyShortLabel('sanyuan-tail-v1')).toBe('三源尾盘共振')
    expect(strategyShortLabel('qianlong-close-v3')).toBe('潜龙出海')
    expect(strategyShortLabel('yangshi-tail-v1')).toBe('杨氏尾盘选股')
  })

  it('keeps the 已下线 marker because it is status, not annotation', () => {
    expect(strategyShortLabel('sanyuan-tail-1450')).toBe('三源尾盘（已下线）')
  })

  it('passes the em dash through', () => {
    expect(strategyShortLabel(null)).toBe('—')
  })
})
