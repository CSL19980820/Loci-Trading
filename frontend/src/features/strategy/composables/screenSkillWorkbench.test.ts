import { describe, expect, it } from 'vitest'

import type { ScreenSkillCatalogSnippet } from '@/shared/types/quant'

import { createEmptyScreenSkillDraft } from './screenSkillDraft'
import {
  applyCatalogSnippet,
  buildAiRevisionInstruction,
  switchScreenSkillRuntime,
} from './screenSkillWorkbench'

const pythonSnippet: ScreenSkillCatalogSnippet = {
  id: 'python-breakout',
  title: 'Python 突破',
  runtime: 'python',
  dialect: 'python',
  summary: '使用 Python 计算突破信号。',
  code: 'def compute(panels, params):\n    return {"signals": panels["close"] > 0}',
  required_fields: ['close', 'turnover'],
  params: {
    LOOKBACK: { type: 'int', default: 20, min: 5, max: 120, label: '回看周期' },
  },
  factors: ['BREAKOUT', 'TURNOVER'],
}

const formulaSnippet: ScreenSkillCatalogSnippet = {
  id: 'formula-breakout',
  title: '公式突破',
  runtime: 'formula',
  dialect: 'loci',
  summary: '使用公式计算突破信号。',
  code: 'PICK: CLOSE > MA(CLOSE, N);',
  required_fields: ['close', 'volume'],
  params: {
    N: { type: 'int', default: 20, min: 5, max: 120, label: '均线周期' },
  },
  factors: ['BASE_MA'],
}

describe('screenSkillWorkbench helpers', () => {
  it('bounds AI context and marks a truncated current draft', () => {
    const draft = createEmptyScreenSkillDraft()
    draft.formula = 'A'.repeat(600)
    draft.logic[0] = {
      id: 'trend',
      title: '趋势确认',
      expression: 'CLOSE > MA(CLOSE, N)',
      explanation: '价格站上均线后才继续筛选。',
      citationsText: 'ref_trend',
    }

    const context = buildAiRevisionInstruction(draft, '把趋势规则改成放量突破', 320)

    expect(context.length).toBeLessThanOrEqual(320)
    expect(context).toContain('当前草稿正文已截断')
    expect(context).toContain('用户要求：把趋势规则改成放量突破')
    expect(context).toContain('趋势确认')
  })

  it('switches formula and Python while retaining both source buffers', () => {
    const draft = createEmptyScreenSkillDraft()
    draft.formula = 'PICK: CLOSE > OPEN;'
    draft.code = 'def compute(panels, params):\n    return {"signals": panels["close"] > 0}'

    switchScreenSkillRuntime(draft, 'python')
    expect(draft.runtime).toBe('python')
    expect(draft.code).toContain('def compute')
    expect(draft.formula).toBe('PICK: CLOSE > OPEN;')

    switchScreenSkillRuntime(draft, 'formula')
    expect(draft.runtime).toBe('formula')
    expect(draft.formula).toBe('PICK: CLOSE > OPEN;')
    expect(draft.code).toContain('def compute')
  })

  it('applies every snippet contract field without clearing the inactive runtime source', () => {
    const draft = createEmptyScreenSkillDraft()
    draft.formula = 'PICK: CLOSE > OPEN;'

    applyCatalogSnippet(draft, pythonSnippet)

    expect(draft.runtime).toBe('python')
    expect(draft.code).toBe(pythonSnippet.code)
    expect(draft.formula).toBe('PICK: CLOSE > OPEN;')
    expect(draft.dataFields).toEqual(expect.arrayContaining(['close', 'turnover']))
    expect(draft.params).toEqual([
      { key: 'LOOKBACK', type: 'int', defaultValue: '20', min: '5', max: '120', label: '回看周期' },
    ])
    expect(draft.factorsText).toBe('BREAKOUT, TURNOVER')

    applyCatalogSnippet(draft, formulaSnippet)

    expect(draft.runtime).toBe('formula')
    expect(draft.formula).toBe(formulaSnippet.code)
    expect(draft.code).toBe(pythonSnippet.code)
    expect(draft.dataFields).toEqual(expect.arrayContaining(['close', 'turnover', 'volume']))
    expect(draft.params).toEqual([
      { key: 'N', type: 'int', defaultValue: '20', min: '5', max: '120', label: '均线周期' },
    ])
    expect(draft.factorsText).toBe('BASE_MA')
  })
})
