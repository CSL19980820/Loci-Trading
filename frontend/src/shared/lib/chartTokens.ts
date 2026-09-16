/**
 * 图表颜色的单一来源。
 *
 * ECharts 把颜色画进 canvas，是 `setOption` 那一刻的快照——写死 hex 或只在初始化读一次
 * CSS 变量，换主题后 canvas 都不会跟着变。结果就是深色档下 K 线的红绿和表格数字的红绿
 * 是两组不同的红绿。这里把 token 一次性读出来交给 option 构造函数，配合 `useChartTheme`
 * 在主题切换时重新读取并触发重绘。
 */

export type ChartTokens = {
  up: string
  down: string
  warn: string
  info: string
  seal: string
  ink: string
  muted: string
  mist: string
  rule: string
  sheet: string
  /** 均线调色板；索引即第 N 条均线 */
  maPalette: string[]
  mono: string
}

/** SSR / 测试环境下没有真实 CSSOM 时的兜底，取默认「日间 + 朱红」档 */
const FALLBACK: ChartTokens = {
  up: '#c8282a',
  down: '#00793a',
  warn: '#a05e00',
  info: '#1174b4',
  seal: '#cc323e',
  ink: '#192029',
  muted: '#4d5560',
  mist: '#626a73',
  rule: '#cdd1d8',
  sheet: '#fcfdfe',
  maPalette: ['#c8282a', '#1174b4', '#a05e00', '#7c3aed', '#00793a', '#0891b2', '#be185d', '#ca8a04'],
  mono: '"JetBrains Mono", "SF Mono", "Roboto Mono", Consolas, Menlo, monospace',
}

/**
 * ECharts 不认 `color-mix()` / `var()`，只吃具体色值，所以这里必须把变量解析成字面量。
 * getComputedStyle 返回的已是计算值，color-mix 会被求值成 rgb()。
 */
export function readChartTokens(): ChartTokens {
  if (typeof window === 'undefined' || typeof document === 'undefined') return FALLBACK
  const cs = getComputedStyle(document.documentElement)
  const read = (name: string, fallback: string): string => cs.getPropertyValue(name).trim() || fallback

  const base: ChartTokens = {
    up: read('--up', FALLBACK.up),
    down: read('--down', FALLBACK.down),
    warn: read('--warn', FALLBACK.warn),
    info: read('--info', FALLBACK.info),
    seal: read('--seal', FALLBACK.seal),
    ink: read('--ink', FALLBACK.ink),
    muted: read('--muted', FALLBACK.muted),
    mist: read('--mist', FALLBACK.mist),
    rule: read('--rule', FALLBACK.rule),
    sheet: read('--sheet', FALLBACK.sheet),
    maPalette: [...FALLBACK.maPalette],
    mono: read('--mono', FALLBACK.mono),
  }
  // 均线用定性区分色：前两条跟随涨跌语义，其余保持稳定色相以免与涨跌混淆
  base.maPalette = [
    base.up,
    base.info,
    base.warn,
    FALLBACK.maPalette[3],
    base.down,
    FALLBACK.maPalette[5],
    FALLBACK.maPalette[6],
    FALLBACK.maPalette[7],
  ]
  return base
}

/** 把色值调成半透明；ECharts 不支持 color-mix，只能自己算 */
export function withAlpha(color: string, alpha: number): string {
  const value = color.trim()
  const hex = value.match(/^#([0-9a-f]{6})$/i)
  if (hex) {
    const n = Number.parseInt(hex[1], 16)
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
  }
  const rgb = value.match(/^rgba?\(([^)]+)\)$/i)
  if (rgb) {
    const parts = rgb[1].split(/[,/\s]+/).filter(Boolean)
    if (parts.length >= 3) return `rgba(${parts[0]}, ${parts[1]}, ${parts[2]}, ${alpha})`
  }
  return value
}
