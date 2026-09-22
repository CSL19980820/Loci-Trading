/**
 * 全局命令面板（⌘K / Ctrl+K）的开关与跨组件事件。
 *
 * 面板本体挂在 App.vue；侧栏搜索入口、快捷键、任何页面都可以调 openCommandPalette()。
 * 「记一条候选 / 预案」这类需要壳层弹窗的动作通过 requestRecord 抛回去，面板自己不持有弹窗。
 */
import { ref, shallowRef } from 'vue'

export type RecordRequestKind = 'candidate' | 'plan'

export const commandPaletteOpen = ref(false)

/** 最近一次「记一笔」请求；App.vue watch 它来打开 RecordDialog */
export const recordRequest = shallowRef<{ kind: RecordRequestKind; at: number } | null>(null)

export function openCommandPalette(): void {
  commandPaletteOpen.value = true
}

export function closeCommandPalette(): void {
  commandPaletteOpen.value = false
}

export function toggleCommandPalette(): void {
  commandPaletteOpen.value = !commandPaletteOpen.value
}

export function requestRecord(kind: RecordRequestKind): void {
  recordRequest.value = { kind, at: Date.now() }
}

/** 是否是「打开命令面板」的组合键：macOS ⌘K，其余 Ctrl+K */
export function isPaletteHotkey(event: KeyboardEvent): boolean {
  if (event.key.toLowerCase() !== 'k') return false
  return event.metaKey || event.ctrlKey
}

/** 显示给用户看的快捷键文案，按平台区分 */
export function paletteHotkeyLabel(): string {
  const isMac =
    typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || '')
  return isMac ? '⌘K' : 'Ctrl K'
}
