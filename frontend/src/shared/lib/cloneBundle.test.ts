import { describe, expect, it } from 'vitest'

import {
  CLONE_DEFAULT_MIN_BARS,
  CLONE_DEFAULT_SIGNAL,
  parseCloneBundleText,
  planBundleImport,
} from './cloneBundle'
import type { CloneBundle } from './cloneBundle'

function makeBundle(overrides: Partial<CloneBundle> = {}): CloneBundle {
  return {
    publish_id: 'PUB-1',
    slug: 'ma-cross',
    title: '均线金叉',
    summary: '5 日线上穿 20 日线买入。',
    kind: 'screen',
    entry_timing: 'next_open',
    owner_name: '老王',
    version: 3,
    source_text: 'PICK: MA(CLOSE, 5) > MA(CLOSE, 20);\n',
    params: {},
    manifest: { backtest: { start: '2020-01-01', end: '2024-01-01', trades: 88 } },
    content_sha256: 'abc123',
    imported_from: 'clone-export',
    ...overrides,
  }
}

describe('planBundleImport / slug', () => {
  it('本地没有同名时原样使用', () => {
    const plan = planBundleImport(makeBundle(), ['other'])
    expect(plan.payload.slug).toBe('ma-cross')
    expect(plan.slugRenamed).toBe(false)
  })

  it('撞名时递增后缀，绝不覆盖本地同名战法', () => {
    const plan = planBundleImport(makeBundle(), ['ma-cross'])
    expect(plan.payload.slug).toBe('ma-cross-2')
    expect(plan.slugRenamed).toBe(true)
    expect(plan.warnings.some((row) => row.includes('ma-cross-2'))).toBe(true)
    expect(plan.warnings.some((row) => row.includes('为免覆盖'))).toBe(true)
  })

  it('连续撞名一路递增到第一个空位', () => {
    const taken = ['ma-cross', 'ma-cross-2', 'ma-cross-3']
    expect(planBundleImport(makeBundle(), taken).payload.slug).toBe('ma-cross-4')
  })

  it('非法字符洗成小写字母 / 数字 / 连字符，并进 warnings', () => {
    const plan = planBundleImport(makeBundle({ slug: '均线 Cross_V2!!' }), [])
    expect(plan.payload.slug).toBe('cross-v2')
    expect(plan.slugRenamed).toBe(true)
    expect(plan.warnings.some((row) => row.includes('不符合本地命名规则'))).toBe(true)
  })

  it('slug 全是非法字符时给个能用的兜底名，而不是空串', () => {
    expect(planBundleImport(makeBundle({ slug: '！！！' }), []).payload.slug).toBe('cloned-skill')
  })
})

describe('planBundleImport / runtime 推断', () => {
  it('正文有 def 行 → python，填 code 与 entrypoint', () => {
    const plan = planBundleImport(
      makeBundle({ source_text: 'def compute(panels, params):\n    return panels\n' }),
      [],
    )
    expect(plan.payload.runtime).toBe('python')
    expect(plan.payload.dialect).toBe('python')
    expect(plan.payload.code).toContain('def compute')
    expect(plan.payload.formula).toBeUndefined()
    expect(plan.payload.entrypoint).toBe('strategy.py:compute')
    expect(plan.warnings.some((row) => row.includes('这是猜的'))).toBe(true)
  })

  it('正文有 import 行 → 同样按 python', () => {
    const plan = planBundleImport(makeBundle({ source_text: 'import pandas as pd\nx = 1\n' }), [])
    expect(plan.payload.runtime).toBe('python')
  })

  it('没有 def / import → formula + loci，填 formula', () => {
    const plan = planBundleImport(makeBundle(), [])
    expect(plan.payload.runtime).toBe('formula')
    expect(plan.payload.dialect).toBe('loci')
    expect(plan.payload.formula).toContain('MA(CLOSE, 5)')
    expect(plan.payload.code).toBeUndefined()
    expect(plan.payload.entrypoint).toBeUndefined()
    // 推断结果一律告警：这是猜的，不是克隆包带过来的
    expect(plan.warnings.some((row) => row.includes('runtime=formula'))).toBe(true)
  })

  it('正文为空时明说会被后端拒绝', () => {
    const plan = planBundleImport(makeBundle({ source_text: '' }), [])
    expect(plan.warnings.some((row) => row.includes('正文是空的'))).toBe(true)
  })
})

describe('planBundleImport / 参数反推', () => {
  it('整数 → int、小数 → float、布尔 → bool', () => {
    const plan = planBundleImport(makeBundle({ params: { fast: 5, ratio: 1.5, strict: true } }), [])
    expect(plan.payload.manifest.params).toEqual({
      fast: { type: 'int', default: 5 },
      ratio: { type: 'float', default: 1.5 },
      strict: { type: 'bool', default: true },
    })
    expect(plan.warnings.some((row) => row.includes('3 个参数是从运行时的值反推'))).toBe(true)
  })

  it('反推不出类型的逐个丢弃并逐个告警', () => {
    const plan = planBundleImport(
      makeBundle({ params: { name: 'MA', codes: ['600000'], cfg: { a: 1 }, nothing: null } }),
      [],
    )
    expect(plan.payload.manifest.params).toEqual({})
    for (const key of ['name', 'codes', 'cfg', 'nothing']) {
      expect(plan.warnings.some((row) => row.includes(`参数「${key}」`))).toBe(true)
    }
    expect(plan.warnings.filter((row) => row.includes('已丢弃')).length).toBe(4)
  })

  it('NaN 这种「是数字但没法当默认值」的也丢掉', () => {
    const plan = planBundleImport(makeBundle({ params: { broken: Number.NaN } }), [])
    expect(plan.payload.manifest.params).toEqual({})
    expect(plan.warnings.some((row) => row.includes('参数「broken」'))).toBe(true)
  })
})

describe('planBundleImport / manifest 重建', () => {
  it('entry_timing 合法就原样带过来', () => {
    const plan = planBundleImport(makeBundle({ entry_timing: 'next_dip' }), [])
    expect(plan.payload.manifest.entry_timing).toBe('next_dip')
    expect(plan.warnings.some((row) => row.includes('已降级'))).toBe(false)
  })

  it('entry_timing 非法时降级到 next_open 并告警', () => {
    const plan = planBundleImport(makeBundle({ entry_timing: 'intraday_whatever' }), [])
    expect(plan.payload.manifest.entry_timing).toBe('next_open')
    expect(
      plan.warnings.some((row) => row.includes('intraday_whatever') && row.includes('next_open')),
    ).toBe(true)
  })

  it('min_bars 用保守默认、factors 留空、schema_version 固定 1', () => {
    const manifest = planBundleImport(makeBundle(), []).payload.manifest
    expect(manifest.min_bars).toBe(CLONE_DEFAULT_MIN_BARS)
    expect(manifest.factors).toEqual([])
    expect(manifest.schema_version).toBe(1)
  })

  it('公式里的信号名读得出就用它，读不出才落回仓内默认值', () => {
    // `NAME :=` 是因子赋值，不是信号；与后端 _SIGNAL_PATTERN 一样跳过它
    expect(planBundleImport(makeBundle(), []).payload.manifest.output.signal).toBe('PICK')
    const custom = planBundleImport(
      makeBundle({ source_text: 'MA5 := MA(CLOSE, 5);\nBUY: MA5 > CLOSE;\n' }),
      [],
    )
    expect(custom.payload.manifest.output.signal).toBe('BUY')
    const python = planBundleImport(makeBundle({ source_text: 'def compute():\n    pass\n' }), [])
    expect(python.payload.manifest.output.signal).toBe(CLONE_DEFAULT_SIGNAL)
  })

  it('原作者的回测证据不进本地 manifest，但要在 warnings 里点名', () => {
    const plan = planBundleImport(makeBundle(), [])
    expect('backtest' in plan.payload.manifest).toBe(false)
    expect(
      plan.warnings.some((row) => row.includes('2020-01-01 ~ 2024-01-01') && row.includes('88 笔')),
    ).toBe(true)
    expect(plan.warnings.some((row) => row.includes('重跑回测'))).toBe(true)
  })

  it('没有回测证据时也要说清「你得自己跑一次」', () => {
    const plan = planBundleImport(makeBundle({ manifest: {} }), [])
    expect(plan.warnings.some((row) => row.includes('没有可读的回测证据'))).toBe(true)
  })
})

describe('planBundleImport / 文案与来源标注', () => {
  it('description = 摘要 + 一行来源标注', () => {
    const plan = planBundleImport(makeBundle(), [])
    expect(plan.payload.description).toBe('5 日线上穿 20 日线买入。\n克隆自 @老王 的【均线金叉】v3')
    expect(plan.payload.name).toBe('均线金叉')
    expect(plan.payload.version).toBe('0.1.0')
    expect(plan.payload.enabled).toBe(true)
  })

  it('作者匿名时来源标注仍然成立，不留空洞', () => {
    const plan = planBundleImport(makeBundle({ owner_name: '', summary: '' }), [])
    expect(plan.payload.description).toBe('克隆自 @匿名作者 的【均线金叉】v3')
  })

  it('摘要过长时截断，且截断这件事本身要告警', () => {
    const plan = planBundleImport(makeBundle({ summary: '很长'.repeat(200) }), [])
    expect(plan.payload.description.length).toBeLessThanOrEqual(240)
    expect(plan.payload.description).toContain('克隆自 @老王')
    expect(plan.warnings.some((row) => row.includes('已截断'))).toBe(true)
  })
})

describe('parseCloneBundleText', () => {
  it('合法 JSON 解析成 bundle', () => {
    const result = parseCloneBundleText(JSON.stringify(makeBundle()))
    expect(result.ok).toBe(true)
    if (result.ok) expect(result.bundle.slug).toBe('ma-cross')
  })

  it('空输入提示「粘贴框是空的」', () => {
    const result = parseCloneBundleText('   ')
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.error).toContain('粘贴框是空的')
  })

  it('粘了一半（缺右大括号）提示没粘全', () => {
    const result = parseCloneBundleText('{"slug": "ma-cross"')
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.error).toContain('没粘全')
  })

  it('压根不是 JSON 时提示该粘什么', () => {
    const result = parseCloneBundleText('已复制克隆包到剪贴板')
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.error).toContain('不是合法 JSON')
  })

  it('只粘了 manifest 那一块时逐个点名缺失字段', () => {
    const result = parseCloneBundleText(JSON.stringify({ backtest: { trades: 30 } }))
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.error).toContain('slug')
      expect(result.error).toContain('title')
      expect(result.error).toContain('source_text')
    }
  })

  it('粘成数组时也说人话', () => {
    const result = parseCloneBundleText('[1, 2]')
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.error).toContain('数组')
  })

  it('缺席的可选字段补成安全默认，不至于让下游炸', () => {
    const result = parseCloneBundleText(
      JSON.stringify({ slug: 'x', title: 'X', source_text: 'A: 1;', params: 'bad' }),
    )
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.bundle.params).toEqual({})
    expect(result.bundle.manifest).toEqual({})
    const plan = planBundleImport(result.bundle, [])
    expect(plan.payload.slug).toBe('x')
  })
})
