/**
 * 主题：外观（明暗 + 中性色性格）× 主色（内置色板 + 用户自定义）。
 *
 * 三层令牌（见 style.base.css / style.theme.css 的文件头）：
 *   ① 原色阶 primitive（--n-1..--n-12 / 主色阶）
 *   ② 语义层 semantic（--surface* / --border-* / --text-*）
 *   ③ 组件层（EP 桥接、Sheet、表格）
 * 这里只负责 ①② 里「随用户选择而变」的那部分：往 <html> 上挂
 * data-appearance / data-primary，以及自定义主色时把算好的色阶写成内联变量。
 *
 * 为什么主色要在 TS 里算：
 *   用户可以选**任意** hex。直接把它塞进 --seal，白底上的按钮文字随时会看不见
 * （比如选了淡黄 #FFFACD）。所以走 OKLCH：**只取用户颜色的色相 h 与彩度 c，
 *   亮度 L 由系统按色阶位置钉死**，再用 WCAG 对比度做一次收敛校正。
 *   OKLCH 是感知均匀色空间，同一 L 下不同色相亮度一致（HSL 做不到），
 *   这是「任意主色都不翻车」的关键。
 *
 * 为什么输出是 hex 而不是 oklch()：
 *   ECharts/zrender 的颜色解析只认 hex / rgb / rgba / hsl（见
 *   node_modules/zrender/lib/tool/color.js 的 parse），Monaco 的 defineTheme 只认 hex。
 *   这些消费方通过 getComputedStyle 读 --seal / --up 等令牌，而自定义属性的计算值
 *   是原样 token 串（oklch() 不会被求值成 rgb）。所以「会被 JS 读走的令牌」一律落成 sRGB 字面量。
 */

export type ThemeMode = 'light' | 'dark'

export interface AppearancePreview {
  /** 页面画布 */
  canvas: string
  /** 区块面板 */
  surface: string
  /** 分隔线 */
  border: string
  /** 正文 */
  text: string
}

export interface AppearanceOption {
  id: string
  label: string
  mode: ThemeMode
  /** 单色速览（存量调用方 SysAppearanceSection 用它画小圆点） */
  swatch: string
  /** 性格一句话，≤ 8 字 */
  hint: string
  /** 真实配色预览：让用户在选之前就看出四档不是同一张脸 */
  preview: AppearancePreview
}

export interface PrimaryOption {
  id: string
  label: string
  /** 明亮档实心色（已按对比度校正） */
  color: string
}

/** derivePrimaryScale 的产物：键就是 CSS 变量名 */
export interface PrimaryScale {
  '--seal': string
  '--seal-hover': string
  '--seal-active': string
  '--seal-ink': string
  '--seal-soft': string
  '--seal-border': string
  '--on-primary': string
}

/** 自定义主色需要清理/写入的全部内联变量 */
export const PRIMARY_SCALE_VARS: (keyof PrimaryScale)[] = [
  '--seal',
  '--seal-hover',
  '--seal-active',
  '--seal-ink',
  '--seal-soft',
  '--seal-border',
  '--on-primary',
]

/* ───────────────────────── 色彩数学：sRGB ⇄ OKLCH ───────────────────────── */

interface Rgb {
  r: number
  g: number
  b: number
}

export interface Oklch {
  l: number
  c: number
  h: number
}

function clamp(v: number, lo: number, hi: number): number {
  return v < lo ? lo : v > hi ? hi : v
}

/** '#abc' / '#aabbcc' / 'aabbcc' → 0..1 的线性前 sRGB 分量；解析失败返回 null */
export function parseHex(input: string): Rgb | null {
  const raw = String(input || '')
    .trim()
    .replace(/^#/, '')
  const hex = raw.length === 3 ? raw.replace(/(.)/g, '$1$1') : raw
  if (!/^[0-9a-fA-F]{6}$/.test(hex)) return null
  const n = Number.parseInt(hex, 16)
  return { r: ((n >> 16) & 255) / 255, g: ((n >> 8) & 255) / 255, b: (n & 255) / 255 }
}

function toHex2(v: number): string {
  return Math.round(clamp(v, 0, 1) * 255)
    .toString(16)
    .padStart(2, '0')
}

export function rgbToHex(rgb: Rgb): string {
  return `#${toHex2(rgb.r)}${toHex2(rgb.g)}${toHex2(rgb.b)}`
}

function srgbToLinear(c: number): number {
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
}

function linearToSrgb(c: number): number {
  return c <= 0.0031308 ? c * 12.92 : 1.055 * c ** (1 / 2.4) - 0.055
}

/** sRGB → OKLCH（Björn Ottosson 的矩阵） */
export function rgbToOklch(rgb: Rgb): Oklch {
  const r = srgbToLinear(rgb.r)
  const g = srgbToLinear(rgb.g)
  const b = srgbToLinear(rgb.b)
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
  const okL = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s
  const okA = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s
  const okB = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s
  const c = Math.hypot(okA, okB)
  let h = (Math.atan2(okB, okA) * 180) / Math.PI
  if (h < 0) h += 360
  return { l: okL, c, h }
}

function oklchToRgbRaw(color: Oklch): Rgb {
  const hr = (color.h * Math.PI) / 180
  const a = color.c * Math.cos(hr)
  const b = color.c * Math.sin(hr)
  const l_ = color.l + 0.3963377774 * a + 0.2158037573 * b
  const m_ = color.l - 0.1055613458 * a - 0.0638541728 * b
  const s_ = color.l - 0.0894841775 * a - 1.291485548 * b
  const l = l_ * l_ * l_
  const m = m_ * m_ * m_
  const s = s_ * s_ * s_
  return {
    r: linearToSrgb(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
    g: linearToSrgb(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
    b: linearToSrgb(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s),
  }
}

function inGamut(rgb: Rgb): boolean {
  const eps = 1e-4
  const ok = (v: number): boolean => v >= -eps && v <= 1 + eps
  return ok(rgb.r) && ok(rgb.g) && ok(rgb.b)
}

/**
 * OKLCH → sRGB hex。超出 sRGB 色域时**保持 L 与 h、二分压低 c**
 * （而不是简单 clip 通道——clip 会同时改亮度和色相，正是「自定义色失控」的老路）。
 */
export function oklchToHex(color: Oklch): string {
  const l = clamp(color.l, 0, 1)
  const h = ((color.h % 360) + 360) % 360
  let lo = 0
  let hi = Math.max(0, color.c)
  if (inGamut(oklchToRgbRaw({ l, c: hi, h }))) {
    return rgbToHex(oklchToRgbRaw({ l, c: hi, h }))
  }
  for (let i = 0; i < 24; i += 1) {
    const mid = (lo + hi) / 2
    if (inGamut(oklchToRgbRaw({ l, c: mid, h }))) lo = mid
    else hi = mid
  }
  const out = oklchToRgbRaw({ l, c: lo, h })
  return rgbToHex({ r: clamp(out.r, 0, 1), g: clamp(out.g, 0, 1), b: clamp(out.b, 0, 1) })
}

export function hexToOklch(hex: string): Oklch | null {
  const rgb = parseHex(hex)
  return rgb ? rgbToOklch(rgb) : null
}

/** WCAG 2.1 相对亮度 */
export function relativeLuminance(hex: string): number {
  const rgb = parseHex(hex) ?? { r: 0, g: 0, b: 0 }
  return (
    0.2126 * srgbToLinear(rgb.r) + 0.7152 * srgbToLinear(rgb.g) + 0.0722 * srgbToLinear(rgb.b)
  )
}

/** WCAG 2.1 对比度，返回 1..21 */
export function contrastRatio(a: string, b: string): number {
  const la = relativeLuminance(a)
  const lb = relativeLuminance(b)
  const hi = Math.max(la, lb)
  const lo = Math.min(la, lb)
  return (hi + 0.05) / (lo + 0.05)
}

/* ───────────────────────── 主色阶推导 ───────────────────────── */

/** 主色上的文字：超过这个 OKLCH 亮度就该换成深色字（业界惯例 ≈ 0.62） */
export const ON_PRIMARY_L_THRESHOLD = 0.62
/** 实心主色对 --on-primary 必须达到的对比度（WCAG AA 正文档） */
export const MIN_ON_PRIMARY_CONTRAST = 4.5
/** 深色字不用纯黑：纯黑在彩色底上发脏 */
const ON_PRIMARY_DARK = '#14181f'
const ON_PRIMARY_LIGHT = '#ffffff'

/**
 * 亮度阶梯。实心色不是钉死一个 L，而是把用户颜色的 L **夹进一条安全带**：
 * 带内保留用户意图（选亮色就亮一点），带外强行拉回。带宽两端都还留着
 * fitSolid 的对比度收敛兜底，所以任何输入都不会翻车。
 */
const LADDER: Record<
  ThemeMode,
  { minL: number; maxL: number; hoverDelta: number; activeDelta: number; ink: number }
> = {
  // 明亮档：白字在 L≈0.56 处恰好过 4.5；再亮就会被 fitSolid 判给深色字
  light: { minL: 0.5, maxL: 0.72, hoverDelta: -0.06, activeDelta: -0.12, ink: 0.45 },
  // 深色档：实心色整体抬高（深底上要跳出来），hover 往亮走而不是往暗走
  dark: { minL: 0.55, maxL: 0.78, hoverDelta: 0.07, activeDelta: 0.13, ink: 0.82 },
}

/** 彩度上限：用户选到荧光色时压一压，避免整屏刺眼；下限不设（纯灰主色是合法选择） */
const MAX_CHROMA = 0.19

function rgbaOf(hex: string, alpha: number): string {
  const rgb = parseHex(hex) ?? { r: 0, g: 0, b: 0 }
  const to255 = (v: number): number => Math.round(clamp(v, 0, 1) * 255)
  return `rgba(${to255(rgb.r)}, ${to255(rgb.g)}, ${to255(rgb.b)}, ${alpha})`
}

/**
 * 钉住色相/彩度，从目标亮度出发收敛出一个「对 on-primary 一定达标」的实心色。
 * 白字就往暗走、深字就往亮走，单向移动所以不会来回横跳。
 */
function fitSolid(h: number, c: number, targetL: number): { hex: string; on: string } {
  const on = targetL > ON_PRIMARY_L_THRESHOLD ? ON_PRIMARY_DARK : ON_PRIMARY_LIGHT
  const step = on === ON_PRIMARY_LIGHT ? -0.01 : 0.01
  let l = targetL
  let hex = oklchToHex({ l, c, h })
  for (let i = 0; i < 60; i += 1) {
    if (contrastRatio(hex, on) >= MIN_ON_PRIMARY_CONTRAST + 0.05) break
    l = clamp(l + step, 0.02, 0.98)
    hex = oklchToHex({ l, c, h })
  }
  return { hex, on }
}

/**
 * 用户选的任意颜色 → 一整套可用的主色阶（纯函数，可单测）。
 *
 * 只取 hex 的 **色相 h 与彩度 c**，亮度 L 由系统按色阶位置决定，再用 WCAG
 * 对比度收敛一次。所以「选了淡黄，按钮却是深黄」是**设计如此**：
 * 淡黄当实心底色时，上面无论白字黑字都难读。
 *
 * @param hex  用户颜色，接受 #rgb / #rrggbb（非法输入回落到默认色）
 * @param mode 当前外观的明暗档——同一个颜色在明暗两档要给不同亮度
 */
export function derivePrimaryScale(hex: string, mode: ThemeMode = 'light'): PrimaryScale {
  const parsed = hexToOklch(hex) ?? hexToOklch(DEFAULT_CUSTOM_COLOR)!
  const h = parsed.h
  const c = Math.min(parsed.c, MAX_CHROMA)
  const ladder = LADDER[mode]

  const solid = fitSolid(h, c, clamp(parsed.l, ladder.minL, ladder.maxL))
  const solidL = hexToOklch(solid.hex)?.l ?? ladder.minL
  const hover = oklchToHex({ l: clamp(solidL + ladder.hoverDelta, 0.08, 0.94), c, h })
  const active = oklchToHex({ l: clamp(solidL + ladder.activeDelta, 0.08, 0.94), c, h })
  // 主色文字（落在页面表面上，不是落在实心主色上）：明档压暗、暗档提亮
  const inkColor = oklchToHex({ l: ladder.ink, c: Math.min(c, 0.16), h })
  // 浅底/描边用半透明：同一个值在四个外观的表面上都成立，不用为深色再写一份
  const soft = rgbaOf(solid.hex, mode === 'light' ? 0.12 : 0.22)
  const border = rgbaOf(solid.hex, mode === 'light' ? 0.45 : 0.55)

  return {
    '--seal': solid.hex,
    '--seal-hover': hover,
    '--seal-active': active,
    '--seal-ink': inkColor,
    '--seal-soft': soft,
    '--seal-border': border,
    '--on-primary': solid.on,
  }
}

/* ───────────────────────── 外观与内置主色 ───────────────────────── */

/**
 * 四档外观。区别**不只是明暗**：中性色的色相倾向（冷灰 / 暖米 / 蓝灰 / 纯黑）、
 * 对比度强度、表面层级差都不一样。
 *
 * preview 的四个色值 = style.theme.css 里该档 --n-3 / --n-2 / --n-7 / --n-12 的兑现值
 *（画布 / 面板 / 边框 / 正文），弹窗靠它画「真实配色预览」。改色阶要同步这里。
 */
export const APPEARANCE_OPTIONS: AppearanceOption[] = [
  {
    id: 'day',
    label: '日间',
    mode: 'light',
    swatch: '#f3f5f8',
    hint: '冷中性灰',
    preview: { canvas: '#f3f5f8', surface: '#fafbfd', border: '#d0d6dc', text: '#1b252f' },
  },
  {
    id: 'paper',
    label: '暖纸',
    mode: 'light',
    swatch: '#fbf1e1',
    hint: '暖米护眼',
    preview: { canvas: '#fbf1e1', surface: '#fff8ed', border: '#ded2be', text: '#2c261b' },
  },
  {
    id: 'night',
    label: '夜间',
    mode: 'dark',
    swatch: '#0e141c',
    hint: '蓝灰科技',
    preview: { canvas: '#0e141c', surface: '#171e27', border: '#2f3640', text: '#f0f4f9' },
  },
  {
    id: 'ink',
    label: '墨黑',
    mode: 'dark',
    swatch: '#070707',
    hint: '纯黑高反差',
    preview: { canvas: '#070707', surface: '#131313', border: '#2e2e2e', text: '#ffffff' },
  },
]

/**
 * 内置主色。色值是 derivePrimaryScale(种子色, 'light')['--seal'] 的产出，
 * 与 style.theme.css 里 html[data-primary=...] 的 --seal **必须逐字一致**
 *（theme.test.ts 会验：拿这里的值再跑一遍推导，结果不变才算没漂）。
 */
export const PRIMARY_OPTIONS: PrimaryOption[] = [
  { id: 'seal', label: '朱红', color: '#cc323e' },
  { id: 'flame', label: '橙红', color: '#c15108' },
  { id: 'amber', label: '琥珀', color: '#d79700' },
  { id: 'moss', label: '墨绿', color: '#298646' },
  { id: 'lake', label: '湖绿', color: '#008471' },
  { id: 'teal', label: '青青', color: '#007ca8' },
  { id: 'blue', label: '靖蓝', color: '#396ed6' },
  { id: 'violet', label: '紫罗兰', color: '#854ece' },
]

/**
 * 自定义主色的推荐色（喂给 el-color-picker 的 :predefine）。
 * 前八个就是内置色板，后两个是内置里没有的桃红与石墨——给「我想要点别的」一个起点。
 */
export const CUSTOM_PRESETS: string[] = [
  '#cc323e',
  '#c15108',
  '#d79700',
  '#298646',
  '#008471',
  '#007ca8',
  '#396ed6',
  '#854ece',
  '#c2417f',
  '#6b7280',
]

export const APPEARANCE_KEY = 'loci-appearance'
export const PRIMARY_KEY = 'loci-primary'
export const CUSTOM_PRIMARY_KEY = 'loci-primary-custom'
export const DEFAULT_APPEARANCE = 'day'
export const DEFAULT_PRIMARY = 'seal'
/** primaryId === CUSTOM_PRIMARY_ID 时，主色从 CUSTOM_PRIMARY_KEY 读 */
export const CUSTOM_PRIMARY_ID = 'custom'
export const DEFAULT_CUSTOM_COLOR = '#3269e0'

export function normalizeAppearance(id: string | null | undefined): string {
  return APPEARANCE_OPTIONS.some((o) => o.id === id) ? String(id) : DEFAULT_APPEARANCE
}

export function normalizePrimary(id: string | null | undefined): string {
  if (id === CUSTOM_PRIMARY_ID) return CUSTOM_PRIMARY_ID
  return PRIMARY_OPTIONS.some((o) => o.id === id) ? String(id) : DEFAULT_PRIMARY
}

/** 非法/缺失一律回落到默认色，不让脏 localStorage 把页面搞成透明 */
export function normalizeCustomColor(value: string | null | undefined): string {
  const rgb = parseHex(value ?? '')
  return rgb ? rgbToHex(rgb) : DEFAULT_CUSTOM_COLOR
}

export function appearanceMode(id: string): ThemeMode {
  return APPEARANCE_OPTIONS.find((o) => o.id === id)?.mode ?? 'light'
}

function safeRead(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function safeWrite(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* 隐私模式下 localStorage 会抛，主题不是关键路径，静默即可 */
  }
}

export function getStoredAppearance(): string {
  return normalizeAppearance(safeRead(APPEARANCE_KEY))
}

export function getStoredPrimary(): string {
  return normalizePrimary(safeRead(PRIMARY_KEY))
}

export function getStoredCustomColor(): string {
  return normalizeCustomColor(safeRead(CUSTOM_PRIMARY_KEY))
}

/**
 * 落地主题。
 *
 * 自定义主色写成**内联变量**（优先级高于 class/属性选择器）；切回内置主色时必须
 * removeProperty 清干净，否则内联值会永久压住 html[data-primary=...]，
 * 表现为「换了主色没反应」。
 */
export function applyTheme(appearanceId: string, primaryId: string, customColor?: string): void {
  const appearance = normalizeAppearance(appearanceId)
  const primary = normalizePrimary(primaryId)
  const root = document.documentElement
  root.setAttribute('data-appearance', appearance)
  root.setAttribute('data-primary', primary)
  root.setAttribute('data-theme', appearance)
  const isDark = appearanceMode(appearance) === 'dark'
  root.style.colorScheme = isDark ? 'dark' : 'light'
  // Element Plus 深色变量以 html.dark 为开关
  root.classList.toggle('dark', isDark)

  if (primary === CUSTOM_PRIMARY_ID) {
    const hex = normalizeCustomColor(customColor ?? getStoredCustomColor())
    const scale = derivePrimaryScale(hex, isDark ? 'dark' : 'light')
    for (const name of PRIMARY_SCALE_VARS) root.style.setProperty(name, scale[name])
    safeWrite(CUSTOM_PRIMARY_KEY, hex)
  } else {
    for (const name of PRIMARY_SCALE_VARS) root.style.removeProperty(name)
  }

  safeWrite(APPEARANCE_KEY, appearance)
  safeWrite(PRIMARY_KEY, primary)
}

export function initTheme(): { appearanceId: string; primaryId: string; customColor: string } {
  const appearanceId = getStoredAppearance()
  const primaryId = getStoredPrimary()
  const customColor = getStoredCustomColor()
  applyTheme(appearanceId, primaryId, customColor)
  return { appearanceId, primaryId, customColor }
}
