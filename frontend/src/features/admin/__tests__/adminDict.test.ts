import { describe, expect, it } from 'vitest'
import { ACTION_OPTIONS, LOGIN_ACTION_OPTIONS, actionLabel } from '../lib/adminDict'

/** 界面上禁止出现机器码：拉丁字母 + 点/下划线的组合一律算漏。 */
const MACHINE_CODE = /[a-z_]+\.[a-z_]+/i

describe('adminDict - 审计动作转中文', () => {
  it('正式字典与遗留别名都命中中文', () => {
    expect(actionLabel('account.login')).toBe('账号登录')
    expect(actionLabel('admin.reset_password')).toBe('重置用户密码')
    // 早期一次性脚本写歪的机器码，库里还有存量行
    expect(actionLabel('account.admin_reset_password')).toBe('重置用户密码')
  })

  it('未登记的 action 走「域·动作」拼词，绝不漏英文', () => {
    expect(actionLabel('ops.export')).toBe('运维·导出')
    expect(actionLabel('account.logout')).toBe('账号·退出登录')
  })

  it('拼不出来时落到「未登记操作」，仍然不是机器码', () => {
    expect(actionLabel('zzz.mystery_thing')).toBe('未登记操作')
    expect(actionLabel('zzz.mystery_thing')).not.toMatch(MACHINE_CODE)
    expect(actionLabel('')).toBe('—')
    expect(actionLabel(null)).toBe('—')
  })

  it('筛选下拉全中文，且不因遗留别名出现重复选项', () => {
    for (const option of [...ACTION_OPTIONS, ...LOGIN_ACTION_OPTIONS]) {
      expect(option.label).not.toMatch(MACHINE_CODE)
    }
    const resetOptions = ACTION_OPTIONS.filter((o) => o.label === '重置用户密码')
    expect(resetOptions).toHaveLength(1)
    expect(resetOptions[0]?.value).toBe('admin.reset_password')
  })
})
