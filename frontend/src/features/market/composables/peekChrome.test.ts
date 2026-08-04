import { describe, expect, it } from 'vitest'

import { shouldShowGhost } from './peekChrome'

describe('shouldShowGhost', () => {
  it('never ghosts while host phase is free', () => {
    expect(shouldShowGhost('free', 22, 22)).toBe(false)
    expect(shouldShowGhost('free', 340, 340)).toBe(false)
  })

  it('ghosts only when collapsed and viewport is tip-sized', () => {
    expect(shouldShowGhost('collapsed', 22, 22)).toBe(true)
    expect(shouldShowGhost('collapsed', 28, 28)).toBe(true)
    expect(shouldShowGhost('collapsed', 40, 40)).toBe(true)
    expect(shouldShowGhost('collapsed', 48, 48)).toBe(true)
  })

  it('keeps opaque free UI when phase is collapsed but window is still free-sized', () => {
    // 复现桌面白方块：prefs peek_collapsed + create_window(340,340)
    expect(shouldShowGhost('collapsed', 340, 340)).toBe(false)
    expect(shouldShowGhost('collapsed', 340, 120)).toBe(false)
    expect(shouldShowGhost('collapsed', 100, 100)).toBe(false)
  })
})
