/** 思考程度选项：同供应商每次调用可不同。 */
export const THINKING_OPTIONS = [
  { value: '', label: '不启思考' },
  { value: 'low', label: '低' },
  { value: 'medium', label: '中' },
  { value: 'high', label: '高' },
] as const

export type ThinkingLevel = (typeof THINKING_OPTIONS)[number]['value']
