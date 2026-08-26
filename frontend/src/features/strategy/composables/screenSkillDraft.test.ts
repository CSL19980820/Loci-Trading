import { describe, expect, it } from 'vitest'

import {
  buildScreenSkillPayload,
  buildScreenSkillReferences,
  createEmptyScreenSkillDraft,
  draftFromGeneratedSkill,
  isCurrentSkillLoad,
} from './screenSkillDraft'

describe('screenSkillDraft helpers', () => {
  it('builds payload with logic, references and manifest data', () => {
    const draft = createEmptyScreenSkillDraft()
    draft.slug = 'breakout'
    draft.name = '突破'
    draft.description = '测试'
    draft.factorsText = 'BASE_MA, BREAKOUT'
    draft.logic = [
      {
        id: 'logic_breakout',
        title: '放量突破',
        expression: 'CLOSE > BASE_MA AND VOL > MA(VOL, 5)',
        explanation: '量价一起确认突破。',
        citationsText: 'ref_handbook',
      },
    ]
    draft.references = [
      {
        id: 'ref_handbook',
        title: '均线突破手册',
        kind: 'doc',
        url: 'https://example.com/ma',
        path: '',
        section: '第 2 节',
        quote: '站上均线后再确认量能。',
      },
    ]
    draft.dataFields = ['close', 'volume', 'turnover']
    draft.adjust = 'hfq'
    draft.boards = ['main', 'bse']
    draft.industriesIncludeText = '半导体\n军工'
    draft.params = [
      {
        key: 'N',
        type: 'int',
        defaultValue: '20',
        min: '5',
        max: '120',
        label: '周期',
      },
      {
        key: 'VOL_MULT',
        type: 'float',
        defaultValue: '1.5',
        min: '1',
        max: '5',
        label: '放量倍数',
      },
    ]

    const { payload, errors } = buildScreenSkillPayload(draft)

    expect(errors).toEqual([])
    expect(payload?.runtime).toBe('formula')
    expect(payload?.manifest.schema_version).toBe(2)
    expect(payload?.manifest.params.N.default).toBe(20)
    expect(payload?.manifest.params.VOL_MULT.default).toBe(1.5)
    expect(payload?.manifest.logic?.[0]?.citations).toEqual(['ref_handbook'])
    expect(payload?.manifest.references?.[0]?.id).toBe('ref_handbook')
    expect(payload?.manifest.data).toEqual({
      fields: ['close', 'volume', 'turnover'],
      adjust: 'hfq',
      universe: {
        preset: null,
        boards: ['main', 'bse'],
        exclude_st: true,
        exclude_delisting: true,
        exclude_suspended: false,
        min_list_days: 60,
        codes_include: [],
        codes_exclude: [],
        industries_include: ['半导体', '军工'],
        industries_exclude: [],
      },
    })
  })

  it('default drafts cover formula and python runtime presets', () => {
    const formulaDraft = createEmptyScreenSkillDraft()
    const pythonDraft = createEmptyScreenSkillDraft('python')

    expect(formulaDraft.runtime).toBe('formula')
    expect(formulaDraft.formula).toContain('MA(CLOSE,N)')
    expect(formulaDraft.dataFields).toContain('close')
    expect(pythonDraft.runtime).toBe('python')
    expect(pythonDraft.dialect).toBe('python')
    expect(pythonDraft.code).toContain('def compute(panels, params)')
    expect(pythonDraft.code).toContain('"signals": signal')
    expect(pythonDraft.entrypoint).toBe('strategy.py:compute')
  })

  it('rejects invalid boolean defaults', () => {
    const draft = createEmptyScreenSkillDraft()
    draft.slug = 'bool-demo'
    draft.name = '布尔'
    draft.description = '测试'
    draft.factorsText = 'FLAG'
    draft.params = [
      {
        key: 'FLAG',
        type: 'bool',
        defaultValue: 'yes',
        min: '',
        max: '',
        label: '',
      },
    ]

    const { payload, errors } = buildScreenSkillPayload(draft)

    expect(payload).toBeNull()
    expect(errors[0]).toContain('是 或 否')
  })

  it('rejects int params that are not integers', () => {
    const draft = createEmptyScreenSkillDraft()
    draft.slug = 'bad-int'
    draft.name = '坏整数'
    draft.description = '测试'
    draft.params = [
      {
        key: 'N',
        type: 'int',
        defaultValue: '20.5',
        min: '5',
        max: '120',
        label: '',
      },
    ]

    const { payload, errors } = buildScreenSkillPayload(draft)

    expect(payload).toBeNull()
    expect(errors[0]).toContain('必须是整数')
  })

  it('rejects defaults outside min max range', () => {
    const draft = createEmptyScreenSkillDraft()
    draft.slug = 'bad-range'
    draft.name = '坏范围'
    draft.description = '测试'
    draft.params = [
      {
        key: 'N',
        type: 'int',
        defaultValue: '121',
        min: '5',
        max: '120',
        label: '',
      },
    ]

    const { payload, errors } = buildScreenSkillPayload(draft)

    expect(payload).toBeNull()
    expect(errors[0]).toContain('必须落在最小值与最大值之间')
  })

  it('rejects min larger than max', () => {
    const draft = createEmptyScreenSkillDraft()
    draft.slug = 'bad-bounds'
    draft.name = '坏边界'
    draft.description = '测试'
    draft.params = [
      {
        key: 'N',
        type: 'int',
        defaultValue: '20',
        min: '50',
        max: '10',
        label: '',
      },
    ]

    const { payload, errors } = buildScreenSkillPayload(draft)

    expect(payload).toBeNull()
    expect(errors[0]).toContain('最小值不能大于最大值')
  })

  it('rejects logic citations that do not map to known references', () => {
    const draft = createEmptyScreenSkillDraft()
    draft.slug = 'cite-miss'
    draft.name = '缺引用'
    draft.description = '测试'
    draft.references = []
    draft.logic = [
      {
        id: 'logic_1',
        title: '逻辑一',
        expression: 'CLOSE > OPEN',
        explanation: '示例说明',
        citationsText: 'ref_missing',
      },
    ]

    const { payload, errors } = buildScreenSkillPayload(draft)

    expect(payload).toBeNull()
    expect(errors[0]).toContain('不存在的资料')
  })

  it('requires explanation for every logic block', () => {
    const draft = createEmptyScreenSkillDraft()
    draft.slug = 'logic-miss-explanation'
    draft.name = '缺逻辑解释'
    draft.description = '测试'
    draft.references = []
    draft.logic = [
      {
        id: 'logic_1',
        title: '逻辑一',
        expression: 'CLOSE > OPEN',
        explanation: '   ',
        citationsText: '',
      },
    ]

    const { payload, errors } = buildScreenSkillPayload(draft)

    expect(payload).toBeNull()
    expect(errors).toContain('逻辑 logic_1 缺少解释')
  })

  it('treats stale skill load as invalid after route switches to no slug', () => {
    expect(isCurrentSkillLoad(3, 4, 'demo-screen', '')).toBe(false)
    expect(isCurrentSkillLoad(4, 4, 'demo-screen', 'demo-screen')).toBe(true)
  })

  it('allows save without any references', () => {
    const draft = createEmptyScreenSkillDraft()
    draft.slug = 'no-ref'
    draft.name = '无资料战法'
    draft.description = '不必填资料也能保存'
    draft.references = [
      {
        id: 'ref_auto',
        title: '',
        kind: 'note',
        url: '',
        path: '',
        section: '',
        quote: '',
      },
    ]

    const { payload, errors } = buildScreenSkillPayload(draft)

    expect(errors).toEqual([])
    expect(payload).not.toBeNull()
    expect(payload?.manifest.references).toEqual([])
  })

  it('collects detailed references for ai generation gating', () => {
    const draft = createEmptyScreenSkillDraft('description')
    draft.references = [
      {
        id: 'ref_1',
        title: '策略笔记',
        kind: 'note',
        url: '',
        path: 'docs/strategy.md',
        section: '第 3 节',
        quote: '放量站上 20 日线。',
      },
    ]

    const built = buildScreenSkillReferences(draft)

    expect(built.errors).toEqual([])
    expect(built.references[0]).toMatchObject({
      id: 'ref_1',
      kind: 'note',
      path: 'docs/strategy.md',
    })
  })

  it('applies generated draft fields without discarding existing revisions', () => {
    const base = createEmptyScreenSkillDraft('python')
    base.packageRevision = 'pkg-1'
    base.strategyRevision = 'rev-1'

    const merged = draftFromGeneratedSkill(
      {
        ok: true,
        diagnostics: [],
        strategy_revision: 'rev-2',
        draft: {
          slug: 'ai-breakout',
          name: 'AI 突破',
          description: '自动生成',
          runtime: 'python',
          dialect: 'python',
          code: 'def compute(panels, params):\n    return {"signals": panels["close"] > panels["open"]}',
          entrypoint: 'strategy.py:compute',
          manifest: {
            schema_version: 2,
            entry_timing: 'next_open',
            min_bars: 30,
            params: {},
            output: { signal: 'PICK' },
            factors: ['PICK'],
            logic: [
              {
                id: 'logic_ai',
                title: 'AI 逻辑',
                expression: 'ctx.close > ctx.open',
                explanation: '最简单示例',
                citations: [],
              },
            ],
            references: [],
            data: {
              fields: ['close', 'open'],
              adjust: 'none',
            },
          },
        },
      },
      base,
    )

    expect(merged.slug).toBe('ai-breakout')
    expect(merged.runtime).toBe('python')
    expect(merged.code).toContain('def compute(panels, params)')
    expect(merged.adjust).toBe('none')
    expect(merged.logic[0]?.id).toBe('logic_ai')
    expect(merged.strategyRevision).toBe('rev-2')
    expect(merged.packageRevision).toBe('pkg-1')
  })
})
