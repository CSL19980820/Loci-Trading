/** LLM 思考程度与模型目录选择器辅助。 */
import type { LlmModel, LlmProvider } from '@/shared/types/quant'

export const THINKING_OPTIONS = [
  { value: '', label: '不启思考' },
  { value: 'low', label: '低' },
  { value: 'medium', label: '中' },
  { value: 'high', label: '高' },
] as const

export type ThinkingLevel = (typeof THINKING_OPTIONS)[number]['value']

export interface LlmModelOption {
  value: string
  label: string
  context_window: number | null
}

/** 把 token 数收成短标签，如 64k / 1M。 */
export function formatContextWindow(tokens: number | null | undefined): string {
  if (tokens == null || tokens <= 0) return ''
  if (tokens >= 1_000_000) {
    const millions = tokens / 1_000_000
    return Number.isInteger(millions) ? `${millions}M` : `${millions.toFixed(1)}M`
  }
  if (tokens >= 1000) return `${Math.round(tokens / 1000)}k`
  return String(tokens)
}

export function formatModelLabel(model: Pick<LlmModel, 'id' | 'name' | 'context_window'>): string {
  const base = model.name && model.name !== model.id ? `${model.name} · ${model.id}` : model.id
  const ctx = formatContextWindow(model.context_window)
  return ctx ? `${base} · ${ctx}` : base
}

/** 其他板块模型下拉：只暴露启用项；兼容缺 model_catalog 的旧响应。 */
export function enabledModelOptions(
  provider: LlmProvider | null | undefined,
): LlmModelOption[] {
  if (!provider) return []
  const catalog = provider.model_catalog
  if (Array.isArray(catalog) && catalog.length > 0) {
    return catalog
      .filter((item) => item.enabled)
      .map((item) => ({
        value: item.id,
        label: formatModelLabel(item),
        context_window: item.context_window,
      }))
  }
  return (provider.models ?? []).map((id) => ({
    value: id,
    label: id,
    context_window: null,
  }))
}
