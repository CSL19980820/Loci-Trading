import { describe, expect, it } from 'vitest'

import {
  fieldErrorMap,
  firstIssueTab,
  issuesFromMessages,
  rowFieldError,
} from './screenSkillDraftIssues'

describe('screenSkillDraftIssues', () => {
  it('routes description and logic errors to strategy tab with field keys', () => {
    const issues = issuesFromMessages([
      '说明不能为空',
      '逻辑 logic_1 缺少解释',
    ])
    expect(firstIssueTab(issues)).toBe('strategy')
    const map = fieldErrorMap(issues)
    expect(map.description).toContain('说明')
    expect(map['logic.id.logic_1.explanation']).toContain('解释')
    expect(rowFieldError(map, 'logic', 0, 'logic_1', 'explanation')).toContain('解释')
  })

  it('jumps to the first error tab and maps reference fields', () => {
    const issues = issuesFromMessages(['资料来源 #1 缺少编号', '至少选择一个数据字段'])
    expect(firstIssueTab(issues)).toBe('references')
    expect(fieldErrorMap(issues)['references.0.id']).toContain('编号')
    expect(fieldErrorMap(issues).dataFields).toContain('数据字段')
  })
})
