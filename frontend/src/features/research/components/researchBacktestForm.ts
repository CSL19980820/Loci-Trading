export type ResearchBacktestFormInput = {
  strategy: string
  range: readonly string[]
  trainRange: readonly string[]
  oosRange: readonly string[]
  historicalUniverseId: string
  strictPit: boolean
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/

function isDate(value: string | undefined): boolean {
  if (!value || !ISO_DATE.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}

function validPair(value: readonly string[]): value is readonly [string, string] {
  return value.length === 2 && isDate(value[0]) && isDate(value[1])
}

/**
 * 在请求前拒绝无法形成严格、预先声明样本的输入；服务端仍是最终门禁。
 */
export function validateResearchBacktestForm(input: ResearchBacktestFormInput): string {
  // 「策略 slug」是给开发看的词：界面上一律说「战法」
  if (!input.strategy.trim()) return '请选择战法'
  if (!validPair(input.range)) return '请填写格式正确的完整回测区间'

  const [start, end] = input.range
  if (start > end) return '回测结束日不能早于开始日'

  const hasTrain = input.trainRange.length > 0
  const hasOos = input.oosRange.length > 0
  if (hasTrain !== hasOos) return '训练区间与 OOS 区间必须成对填写'

  if (!hasTrain) {
    return input.strictPit
      ? '严格 PIT 模式要求完整训练/OOS 区间和历史股票池标识；未满足将拒绝提交'
      : '研究回测必须填写完整训练/OOS 区间；未声明 OOS 的结果不能作为研究证据'
  }
  if (!validPair(input.trainRange) || !validPair(input.oosRange)) {
    return '训练区间与 OOS 区间必须各自填写完整且为有效日期'
  }

  const [trainStart, trainEnd] = input.trainRange
  const [oosStart, oosEnd] = input.oosRange
  if (trainStart > trainEnd) return '训练结束日不能早于训练开始日'
  if (oosStart > oosEnd) return 'OOS 结束日不能早于 OOS 开始日'
  if (trainEnd >= oosStart) return 'OOS 必须严格晚于训练区间，不能重叠或倒序'
  if (trainStart < start || trainEnd > end || oosStart < start || oosEnd > end) {
    return '训练区间和 OOS 区间必须完全位于回测总区间内'
  }
  if (input.strictPit && !input.historicalUniverseId.trim()) {
    return '严格 PIT 模式要求完整训练/OOS 区间和历史股票池标识；未满足将拒绝提交'
  }
  return ''
}
