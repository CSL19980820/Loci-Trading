import { describe, expect, it } from 'vitest'

import { formatApiDetail, toErrorMessage } from '@/shared/lib/errors'

describe('toErrorMessage', () => {
  it('reads Error.message', () => {
    expect(toErrorMessage(new Error('账本繁忙'))).toBe('账本繁忙')
  })

  it('formats FastAPI validation detail arrays', () => {
    expect(
      toErrorMessage({
        detail: [{ msg: '字段必填' }, { message: '格式错误' }],
      }),
    ).toBe('字段必填；格式错误')
  })

  it('does not leak [object Object]', () => {
    expect(toErrorMessage({ foo: 1 }, '加载失败')).toBe('加载失败')
    expect(formatApiDetail({ nested: true }, 422)).toBe('请求失败（422）')
  })
})
