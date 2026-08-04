/**
 * Peek 缩进态必须同时满足：宿主 phase=collapsed，且视口已是探头尺寸。
 * 宿主常以 340² free 窗体挂着 collapsed phase —— 只认 phase 会画透明壳 → 白方块。
 */
export const PEEK_GHOST_VIEWPORT_MAX = 48

export function shouldShowGhost(
  phase: 'free' | 'collapsed',
  viewportWidth: number,
  viewportHeight: number,
): boolean {
  if (phase !== 'collapsed') return false
  return (
    viewportWidth > 0
    && viewportHeight > 0
    && viewportWidth <= PEEK_GHOST_VIEWPORT_MAX
    && viewportHeight <= PEEK_GHOST_VIEWPORT_MAX
  )
}
