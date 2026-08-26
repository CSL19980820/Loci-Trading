/** 把未知错误收成可读中文，避免 el-alert 出现 [object Object]。 */

/** FastAPI / Pydantic 英文校验句 → 中文。 */
function localizeValidation(msg: string): string {
  const t = msg.trim()
  if (!t) return t
  const le = /^Input should be less than or equal to (-?\d+(?:\.\d+)?)$/i.exec(t)
  if (le) return `数值不能超过 ${le[1]}`
  const ge = /^Input should be greater than or equal to (-?\d+(?:\.\d+)?)$/i.exec(t)
  if (ge) return `数值不能小于 ${ge[1]}`
  const lt = /^Input should be less than (-?\d+(?:\.\d+)?)$/i.exec(t)
  if (lt) return `数值须小于 ${lt[1]}`
  const gt = /^Input should be greater than (-?\d+(?:\.\d+)?)$/i.exec(t)
  if (gt) return `数值须大于 ${gt[1]}`
  if (/^Field required$/i.test(t)) return '必填项未填写'
  if (/^Input should be a valid number$/i.test(t)) return '请输入有效数字'
  if (/^Input should be a valid integer$/i.test(t)) return '请输入整数'
  if (/^String should have at most (\d+) characters$/i.test(t)) {
    return t.replace(/^String should have at most (\d+) characters$/i, '文字不能超过 $1 字')
  }
  return t
}

function fromDetail(detail: unknown): string | null {
  if (detail == null) return null
  if (typeof detail === 'string') {
    const t = localizeValidation(detail)
    return t || null
  }
  if (typeof detail === 'number' || typeof detail === 'boolean') return String(detail)
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === 'string') return localizeValidation(item)
        if (item && typeof item === 'object') {
          const row = item as { msg?: unknown; message?: unknown; detail?: unknown; loc?: unknown }
          const raw = String(row.msg ?? row.message ?? row.detail ?? '').trim()
          const localized = localizeValidation(raw)
          if (!localized) return ''
          // 带上字段名，避免只剩「数值不能超过 1000」却不知哪个框
          if (Array.isArray(row.loc) && row.loc.length) {
            const field = row.loc.filter((x) => x !== 'body' && x !== 'query').join('.')
            return field ? `${field}：${localized}` : localized
          }
          return localized
        }
        return ''
      })
      .filter(Boolean)
    return parts.length ? parts.join('；') : null
  }
  if (typeof detail === 'object') {
    const row = detail as { message?: unknown; msg?: unknown; detail?: unknown; error?: unknown }
    const nested = fromDetail(row.message ?? row.msg ?? row.detail ?? row.error)
    if (nested) return nested
  }
  return null
}

export function toErrorMessage(
  caught: unknown,
  fallback = '没读到数据，确认本机服务还在运行',
): string {
  if (caught == null || caught === false) return ''
  if (typeof caught === 'string') {
    const t = caught.trim()
    return t && t !== '[object Object]' ? t : fallback
  }
  if (caught instanceof Error) {
    const msg = caught.message?.trim()
    if (msg && msg !== '[object Object]') return msg
    return fallback
  }
  if (typeof caught === 'object') {
    const row = caught as {
      message?: unknown
      msg?: unknown
      detail?: unknown
      error?: unknown
      cause?: unknown
    }
    const fromFields = fromDetail(row.message ?? row.msg ?? row.detail ?? row.error ?? row.cause)
    if (fromFields && fromFields !== '[object Object]') return fromFields
  }
  return fallback
}

/** FastAPI / 网关 JSON 错误体的 detail 字段。 */
export function formatApiDetail(detail: unknown, status: number): string {
  return fromDetail(detail) || `请求失败（${status}）`
}
