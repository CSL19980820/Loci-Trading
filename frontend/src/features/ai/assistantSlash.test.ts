import { describe, expect, it } from 'vitest'

import {
  applySlashSelection,
  BUILTIN_SLASH_COMMANDS,
  detectSlashTrigger,
  filterSlashSkills,
} from './assistantSlash'

describe('assistantSlash', () => {
  it('detects bare slash on its own line', () => {
    expect(detectSlashTrigger('/')).toEqual({ query: '', lineStart: 0 })
    expect(detectSlashTrigger('/foo')).toEqual({ query: 'foo', lineStart: 0 })
    expect(detectSlashTrigger('hello\n/bar')).toEqual({ query: 'bar', lineStart: 6 })
  })

  it('ignores slash with surrounding text on the same line', () => {
    expect(detectSlashTrigger('a /b')).toBeNull()
    expect(detectSlashTrigger('/b c')).toBeNull()
  })

  it('applies selection by clearing slash line', () => {
    expect(applySlashSelection('/wei', { query: 'wei', lineStart: 0 }, '')).toBe('')
    expect(applySlashSelection('note\n/wei', { query: 'wei', lineStart: 5 }, '')).toBe('note')
  })

  it('filters skills by query', () => {
    const items = [
      { slug: 'weipan', name: '微盘', description: '尾盘' },
      { slug: 'review', name: '复盘', description: '' },
    ]
    expect(filterSlashSkills(items, 'wei').map((item) => item.slug)).toEqual(['weipan'])
  })

  it('exposes builtin /compact and filters it in the slash menu', () => {
    expect(BUILTIN_SLASH_COMMANDS.some((row) => row.slug === 'compact' && row.builtin)).toBe(true)
    const merged = [...BUILTIN_SLASH_COMMANDS, { slug: 'weipan', name: '微盘' }]
    expect(filterSlashSkills(merged, 'comp').map((row) => row.slug)).toEqual(['compact'])
  })
})
