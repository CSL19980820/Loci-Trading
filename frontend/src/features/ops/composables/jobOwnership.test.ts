import { describe, expect, it } from 'vitest'

import {
  isBoundManagedJob,
  isReservedStrategyJobName,
  isSkillBoundJob,
  isStrategyBoundJob,
  jobOriginLabel,
  skillSlugFromBoundJob,
  strategySlugFromBoundJob,
} from './jobOwnership'

describe('jobOwnership', () => {
  it('detects strategy-bound screen jobs by name prefix', () => {
    expect(isStrategyBoundJob({ kind: 'screen', name: 'screen:qianlong-close' })).toBe(true)
    expect(isStrategyBoundJob({ kind: 'screen', name: 'my-screen' })).toBe(false)
    expect(isStrategyBoundJob({ kind: 'sync', name: 'screen:x' })).toBe(false)
  })

  it('detects skill-bound jobs', () => {
    expect(isSkillBoundJob({ kind: 'skill', name: 'skill:dragon-return' })).toBe(true)
    expect(isSkillBoundJob({ kind: 'skill', name: 'adhoc' })).toBe(false)
    expect(isBoundManagedJob({ kind: 'skill', name: 'skill:x' })).toBe(true)
  })

  it('extracts slug and origin label', () => {
    const job = { kind: 'screen' as const, name: 'screen:qianlong-close' }
    expect(strategySlugFromBoundJob(job)).toBe('qianlong-close')
    expect(jobOriginLabel(job)).toBe('战法')
    expect(skillSlugFromBoundJob({ name: 'skill:demo' })).toBe('demo')
    expect(jobOriginLabel({ kind: 'skill', name: 'skill:demo' })).toBe('技能')
    expect(jobOriginLabel({ kind: 'sync', name: '日终同步' })).toBe('本机')
  })

  it('reserves screen: and skill: prefixes for local create names', () => {
    expect(isReservedStrategyJobName('screen:foo')).toBe(true)
    expect(isReservedStrategyJobName('skill:bar')).toBe(true)
    expect(isReservedStrategyJobName(' Screen:Foo ')).toBe(true)
    expect(isReservedStrategyJobName('日终同步')).toBe(false)
  })
})
