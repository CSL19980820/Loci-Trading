/** 主题：外观（明暗）× 主色，参考 gateway-ui 的 data-appearance / data-primary。 */

export interface AppearanceOption {
  id: string
  label: string
  mode: 'light' | 'dark'
  swatch: string
}

export interface PrimaryOption {
  id: string
  label: string
  color: string
}

export const APPEARANCE_OPTIONS: AppearanceOption[] = [
  { id: 'day', label: '日间', mode: 'light', swatch: '#eef2f6' },
  { id: 'paper', label: '暖纸', mode: 'light', swatch: '#f7f4ef' },
  { id: 'night', label: '夜间', mode: 'dark', swatch: '#141b24' },
  { id: 'ink', label: '墨黑', mode: 'dark', swatch: '#0d1117' },
]

export const PRIMARY_OPTIONS: PrimaryOption[] = [
  { id: 'seal', label: '朱红', color: '#c41e3a' },
  { id: 'lake', label: '湖绿', color: '#0f6b5c' },
  { id: 'blue', label: '靛蓝', color: '#2563eb' },
  { id: 'amber', label: '琥珀', color: '#d97706' },
]

export const APPEARANCE_KEY = 'loci-appearance'
export const PRIMARY_KEY = 'loci-primary'
export const DEFAULT_APPEARANCE = 'day'
export const DEFAULT_PRIMARY = 'seal'

export function normalizeAppearance(id: string | null | undefined): string {
  return APPEARANCE_OPTIONS.some((o) => o.id === id) ? String(id) : DEFAULT_APPEARANCE
}

export function normalizePrimary(id: string | null | undefined): string {
  return PRIMARY_OPTIONS.some((o) => o.id === id) ? String(id) : DEFAULT_PRIMARY
}

export function getStoredAppearance(): string {
  return normalizeAppearance(localStorage.getItem(APPEARANCE_KEY))
}

export function getStoredPrimary(): string {
  return normalizePrimary(localStorage.getItem(PRIMARY_KEY))
}

export function applyTheme(appearanceId: string, primaryId: string): void {
  const appearance = normalizeAppearance(appearanceId)
  const primary = normalizePrimary(primaryId)
  const root = document.documentElement
  root.setAttribute('data-appearance', appearance)
  root.setAttribute('data-primary', primary)
  root.setAttribute('data-theme', appearance)
  const meta = APPEARANCE_OPTIONS.find((o) => o.id === appearance)
  root.style.colorScheme = meta?.mode === 'dark' ? 'dark' : 'light'
  localStorage.setItem(APPEARANCE_KEY, appearance)
  localStorage.setItem(PRIMARY_KEY, primary)
}

export function initTheme(): { appearanceId: string; primaryId: string } {
  const appearanceId = getStoredAppearance()
  const primaryId = getStoredPrimary()
  applyTheme(appearanceId, primaryId)
  return { appearanceId, primaryId }
}
