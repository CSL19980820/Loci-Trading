import { readdir, readFile } from 'node:fs/promises'
import { join } from 'node:path'

import { beforeEach, describe, expect, it } from 'vitest'

import {
  APPEARANCE_OPTIONS,
  CUSTOM_PRIMARY_ID,
  CUSTOM_PRIMARY_KEY,
  DEFAULT_APPEARANCE,
  DEFAULT_PRIMARY,
  MIN_ON_PRIMARY_CONTRAST,
  PRIMARY_KEY,
  PRIMARY_OPTIONS,
  PRIMARY_SCALE_VARS,
  applyTheme,
  contrastRatio,
  derivePrimaryScale,
  hexToOklch,
  initTheme,
  normalizeCustomColor,
  normalizePrimary,
  oklchToHex,
} from './theme'

/** 覆盖度足够宽的输入集：极淡、极深、纯灰、荧光、黑白、三位 hex、脏数据 */
const SAMPLES = [
  '#FFFACD', // 极淡黄——最容易在白底上翻车的那一类
  '#000033', // 极深蓝
  '#808080', // 纯灰（无色相可取）
  '#00FF00',
  '#FFFF00',
  '#FF00FF',
  '#ffffff',
  '#000000',
  '#0d9',
  '#c41e3a',
]

describe('derivePrimaryScale', () => {
  it('任意输入的实心主色对 --on-primary 都达到 WCAG AA（≥ 4.5:1）', () => {
    for (const hex of SAMPLES) {
      for (const mode of ['light', 'dark'] as const) {
        const scale = derivePrimaryScale(hex, mode)
        const ratio = contrastRatio(scale['--seal'], scale['--on-primary'])
        expect(
          ratio,
          `${hex} @${mode} → seal=${scale['--seal']} on=${scale['--on-primary']}`,
        ).toBeGreaterThanOrEqual(MIN_ON_PRIMARY_CONTRAST)
      }
    }
  })

  it('内置主色板同样达标（色板值与 CSS 里的 --seal 是同一套算法产出）', () => {
    for (const option of PRIMARY_OPTIONS) {
      const scale = derivePrimaryScale(option.color, 'light')
      expect(contrastRatio(scale['--seal'], scale['--on-primary']), option.id).toBeGreaterThanOrEqual(
        MIN_ON_PRIMARY_CONTRAST,
      )
    }
  })

  it('on-primary 按 OKLCH 亮度分黑白：亮主色配深字，暗主色配白字', () => {
    const pale = derivePrimaryScale('#FFFACD', 'light')
    const deep = derivePrimaryScale('#000033', 'light')
    expect(pale['--on-primary']).not.toBe('#ffffff')
  expect(deep['--on-primary']).toBe('#ffffff')
  })

  it('只取色相与彩度，亮度由系统钉住：淡黄进来必须被压暗', () => {
    const input = hexToOklch('#FFFACD')!
    const out = hexToOklch(derivePrimaryScale('#FFFACD', 'light')['--seal'])!
    expect(out.l).toBeLessThan(input.l - 0.15)
    // 色相守住（±6°），用户还认得出这是自己选的那个颜色
    expect(Math.abs(out.h - input.h)).toBeLessThan(6)
  })

  it('是纯函数：同样输入永远同样输出，且七个键齐备', () => {
    const a = derivePrimaryScale('#3269e0', 'light')
    const b = derivePrimaryScale('#3269e0', 'light')
  expect(a).toEqual(b)
    for (const key of PRIMARY_SCALE_VARS) expect(a[key]).toBeTruthy()
  })

  it('明暗两档给不同的主色文字亮度（--seal-ink 深色档要提亮）', () => {
    const light = hexToOklch(derivePrimaryScale('#c41e3a', 'light')['--seal-ink'])!
    const dark = hexToOklch(derivePrimaryScale('#c41e3a', 'dark')['--seal-ink'])!
    expect(dark.l).toBeGreaterThan(light.l + 0.2)
  })

  it('脏输入不炸：回落到默认色而不是产出空串', () => {
    for (const bad of ['', 'not-a-color', '#12345', null as unknown as string]) {
      const scale = derivePrimaryScale(bad, 'light')
      expect(scale['--seal']).toMatch(/^#[0-9a-f]{6}$/)
    }
  })
})

describe('oklchToHex', () => {
  it('超出 sRGB 色域时压彩度而不是裁通道：亮度与色相要守住', () => {
    // oklch(0.6 0.4 150) 远超 sRGB 绿色域
    const hex = oklchToHex({ l: 0.6, c: 0.4, h: 150 })
    const back = hexToOklch(hex)!
    expect(Math.abs(back.l - 0.6)).toBeLessThan(0.02)
    expect(Math.abs(back.h - 150)).toBeLessThan(4)
  })
})

describe('applyTheme', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('style')
    document.documentElement.removeAttribute('data-appearance')
    document.documentElement.removeAttribute('data-primary')
    document.documentElement.classList.remove('dark')
  })

  it('内置主色不留任何内联色阶变量', () => {
    const root = document.documentElement
    applyTheme('day', 'blue')
    for (const name of PRIMARY_SCALE_VARS) expect(root.style.getPropertyValue(name)).toBe('')
    expect(root.getAttribute('data-primary')).toBe('blue')
  })

  it('自定义主色写内联色阶，切回内置时必须清干净（否则内联优先级会永久卡住主色）', () => {
    const root = document.documentElement
    applyTheme('day', CUSTOM_PRIMARY_ID, '#8b5cf6')
    for (const name of PRIMARY_SCALE_VARS) {
      expect(root.style.getPropertyValue(name), name).not.toBe('')
    }

    applyTheme('day', 'seal')
    for (const name of PRIMARY_SCALE_VARS) {
      expect(root.style.getPropertyValue(name), name).toBe('')
    }
  })

  it('换外观会按明暗重算自定义色阶', () => {
    const root = document.documentElement
    applyTheme('day', CUSTOM_PRIMARY_ID, '#c41e3a')
    const lightInk = root.style.getPropertyValue('--seal-ink')
    applyTheme('night', CUSTOM_PRIMARY_ID, '#c41e3a')
    const darkInk = root.style.getPropertyValue('--seal-ink')
    expect(darkInk).not.toBe(lightInk)
    expect(hexToOklch(darkInk)!.l).toBeGreaterThan(hexToOklch(lightInk)!.l)
  })

  it('深色外观挂 .dark 与 color-scheme，浅色外观摘掉', () => {
    const root = document.documentElement
    applyTheme('ink', 'seal')
    expect(root.classList.contains('dark')).toBe(true)
    expect(root.style.colorScheme).toBe('dark')
    applyTheme('paper', 'seal')
    expect(root.classList.contains('dark')).toBe(false)
    expect(root.style.colorScheme).toBe('light')
  })

  it('落盘 localStorage：自定义色单独一把钥匙', () => {
    applyTheme('night', CUSTOM_PRIMARY_ID, '#00806e')
    expect(localStorage.getItem(PRIMARY_KEY)).toBe(CUSTOM_PRIMARY_ID)
    expect(localStorage.getItem(CUSTOM_PRIMARY_KEY)).toBe('#00806e')
  })

  it('非法外观/主色回落到默认档，不会把属性写成 null', () => {
    const root = document.documentElement
    applyTheme('does-not-exist', 'nope')
  expect(root.getAttribute('data-appearance')).toBe(DEFAULT_APPEARANCE)
    expect(root.getAttribute('data-primary')).toBe(DEFAULT_PRIMARY)
  })
})

describe('initTheme', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('style')
  })

  it('首屏能恢复自定义主色（main.ts 只调这一个入口）', () => {
    localStorage.setItem('loci-appearance', 'ink')
    localStorage.setItem(PRIMARY_KEY, CUSTOM_PRIMARY_ID)
    localStorage.setItem(CUSTOM_PRIMARY_KEY, '#d64c8c')

    const state = initTheme()

    expect(state).toEqual({ appearanceId: 'ink', primaryId: CUSTOM_PRIMARY_ID, customColor: '#d64c8c' })
    const expected = derivePrimaryScale('#d64c8c', 'dark')
    expect(document.documentElement.style.getPropertyValue('--seal')).toBe(expected['--seal'])
  })

  it('localStorage 里是脏数据时回落默认档', () => {
    localStorage.setItem(PRIMARY_KEY, CUSTOM_PRIMARY_ID)
    localStorage.setItem(CUSTOM_PRIMARY_KEY, 'rgb(1,2,3)')
    const state = initTheme()
    expect(state.customColor).toBe(normalizeCustomColor('rgb(1,2,3)'))
    expect(state.customColor).toMatch(/^#[0-9a-f]{6}$/)
  })
})

describe('契约（并行改动方在读这些导出，别改形状）', () => {
  it('外观选项带 mode / swatch / preview', () => {
    expect(APPEARANCE_OPTIONS.map((o) => o.id)).toEqual(['day', 'paper', 'night', 'ink'])
    for (const o of APPEARANCE_OPTIONS) {
      expect(o.swatch).toMatch(/^#[0-9a-f]{6}$/)
      expect(['light', 'dark']).toContain(o.mode)
      expect(Object.keys(o.preview).sort()).toEqual(['border', 'canvas', 'surface', 'text'])
    }
  })

  it('内置主色 6-8 档，且 custom 是合法 id', () => {
    expect(PRIMARY_OPTIONS.length).toBeGreaterThanOrEqual(6)
    expect(PRIMARY_OPTIONS.length).toBeLessThanOrEqual(8)
    expect(normalizePrimary(CUSTOM_PRIMARY_ID)).toBe(CUSTOM_PRIMARY_ID)
    expect(normalizePrimary('bogus')).toBe(DEFAULT_PRIMARY)
  })

  it('内置色板本身就是推导的不动点：再推一次值不变（防 TS 与 CSS 漂移）', () => {
    for (const option of PRIMARY_OPTIONS) {
      expect(derivePrimaryScale(option.color, 'light')['--seal'], option.id).toBe(option.color)
    }
  })

  it('style.theme.css 里每档 --seal 与色板逐字一致', async () => {
    const css = await readFile(join(process.cwd(), 'src/style.theme.css'), 'utf8')
    for (const option of PRIMARY_OPTIONS) {
      const found = new RegExp(
        `html\\[data-primary='${option.id}'\\]\\s*\\{[^}]*--seal:\\s*(#[0-9a-f]{6})`,
        'i',
      ).exec(css)
      expect(found?.[1], `style.theme.css 缺 ${option.id} 或色值不符`).toBe(option.color)
    }
  })

  it('外观预览色与 style.theme.css / style.base.css 的色阶兑现值一致', async () => {
    const base = await readFile(join(process.cwd(), 'src/style.base.css'), 'utf8')
    const theme = await readFile(join(process.cwd(), 'src/style.theme.css'), 'utf8')
    // day 的兑现值落在 base 的 :root，其余三档在 theme 的外观块里
    expect(base).toContain(`--ink: ${APPEARANCE_OPTIONS[0].preview.text};`)
    expect(base).toContain(`--rule: ${APPEARANCE_OPTIONS[0].preview.border};`)
    for (const option of APPEARANCE_OPTIONS.slice(1)) {
      expect(theme, option.id).toContain(`--ink: ${option.preview.text};`)
      expect(theme, option.id).toContain(`--rule: ${option.preview.border};`)
    }
  })
})

/**
 * 令牌向后兼容闸门。
 *
 * 全仓一百多个文件在 `var(--x)` 引用令牌，重构色阶时少定义一个，页面上就是一块
 * 透明/黑块，而且 CSS 不报错、构建不报错、只有人眼能发现。这里把「引用集 ⊆ 定义集」
 * 钉成断言：新加令牌不用管，**删/改名**令牌会立刻红。
 */
const RUNTIME_INJECTED: Record<string, string> = {
  '--sw': 'ThemeDialog / SysAppearanceSection 的色块，:style 内联注入',
  '--bf-span': 'BasicForm 按 schema 算列宽，:style 内联注入',
  '--pc-gap': 'PageContainer :style 内联注入',
  '--pc-padding': 'PageContainer :style 内联注入',
  '--pc-left-width': 'PageContainer :style 内联注入',
  '--kline-vol-top': 'DataQueryDetailPanel :style 内联注入',
  '--kline-ind-top': 'DataQueryDetailPanel :style 内联注入',
  '--token': 'pulseSkin.css 注释里的示意写法，不是真引用',
}

async function collectSourceFiles(dir: string, acc: string[] = []): Promise<string[]> {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) await collectSourceFiles(full, acc)
    // 测试自身的注释里就写着 var(--x) 示例，扫进来会自己咬自己
    else if (/\.(vue|css|ts)$/.test(entry.name) && !/\.(test|spec)\.ts$/.test(entry.name)) {
      acc.push(full)
    }
  }
  return acc
}

describe('令牌向后兼容', () => {
  it('src 下每一个被 var() 引用的令牌都有定义', async () => {
    const files = await collectSourceFiles(join(process.cwd(), 'src'))
    const referenced = new Map<string, string>()
    const defined = new Set<string>(Object.keys(RUNTIME_INJECTED))
    for (const file of files) {
      const text = await readFile(file, 'utf8')
      for (const m of text.matchAll(/var\(\s*(--[a-zA-Z0-9_-]+)/g)) {
        if (!referenced.has(m[1]!)) referenced.set(m[1]!, file)
      }
      for (const m of text.matchAll(/(?:^|[;{\s])(--[a-zA-Z0-9_-]+)\s*:/gm)) defined.add(m[1]!)
    }

    const missing = [...referenced].filter(([name]) => !defined.has(name))
    expect(missing.map(([name, file]) => `${name} <- ${file}`)).toEqual([])
    // 别把断言写成空跑：确认扫描确实命中了核心令牌
    expect(referenced.has('--seal')).toBe(true)
    expect(referenced.size).toBeGreaterThan(100)
  }, 20_000)
})
