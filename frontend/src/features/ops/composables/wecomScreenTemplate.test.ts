import { describe, expect, it } from 'vitest'

import {
  applyWecomPreset,
  normalizeWecomScreenTemplate,
  previewWecomScreenTemplate,
  sameWecomScreenTemplate,
} from './wecomScreenTemplate'

describe('wecomScreenTemplate', () => {
  it('applies compact preset without intro line', () => {
    const tpl = applyWecomPreset(normalizeWecomScreenTemplate(), 'compact')
    const text = previewWecomScreenTemplate(tpl, 'quant')
    expect(text).toContain('【潜龙拐点】-量化')
    expect(text).not.toContain('选股如下')
    expect(text).toContain('📌 龙星科技 300105 +1.5%')
  })

  it('with_date preset includes trade date in intro', () => {
    const tpl = applyWecomPreset(normalizeWecomScreenTemplate(), 'with_date')
    expect(previewWecomScreenTemplate(tpl)).toContain('📅 2026-07-30')
  })

  it('custom tags show in skills preview', () => {
    const tpl = normalizeWecomScreenTemplate({
      preset: 'default',
      skills_tag: '技能',
    })
    expect(previewWecomScreenTemplate(tpl, 'skills')).toContain('【潜龙拐点】-技能')
  })

  it('skills preview appends note after pct with Chinese comma', () => {
    const tpl = normalizeWecomScreenTemplate({ preset: 'default' })
    const text = previewWecomScreenTemplate(tpl, 'skills')
    expect(text).toContain('【潜龙拐点】-技能')
    expect(text).toContain('📌 龙星科技 300105 +1.5%，主线放量站上五日线')
  })

  it('legacy English skill tag is normalized', () => {
    const tpl = normalizeWecomScreenTemplate({ skills_tag: 'skills' })
    expect(tpl.skills_tag).toBe('技能')
    expect(previewWecomScreenTemplate(tpl, 'skills')).not.toContain('skills')
  })

  it('detects dirty template fields', () => {
    const a = normalizeWecomScreenTemplate()
    const b = normalizeWecomScreenTemplate({ quant_tag: '战法' })
    expect(sameWecomScreenTemplate(a, a)).toBe(true)
    expect(sameWecomScreenTemplate(a, b)).toBe(false)
  })

  it('watch section is hidden by default and shown when enabled', () => {
    const off = previewWecomScreenTemplate(normalizeWecomScreenTemplate(), 'quant')
    expect(off).not.toContain('低吸观察')
    expect(off).not.toContain('000957')
    const on = previewWecomScreenTemplate(
      normalizeWecomScreenTemplate({ show_watch_picks: true }),
      'quant',
    )
    expect(on).toContain('👀 低吸观察（不计正式胜率）')
    expect(on).toContain('▫️ 中通客车 000957 +1.66%')
  })

  it('detects watch flag changes as dirty', () => {
    const a = normalizeWecomScreenTemplate()
    const b = normalizeWecomScreenTemplate({ show_watch_picks: true })
    expect(sameWecomScreenTemplate(a, b)).toBe(false)
  })
})
