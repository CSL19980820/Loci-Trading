export type JsonValue = string | number | boolean | null | unknown[] | Record<string, unknown>

/** 数据源下挂了多少个可用接口。 */
/** 出参列名的中英对照。上游多数返回中文列，英文名取自本仓归一映射，缺则留空。 */
export interface ColumnGloss {
  raw: string
  cn: string
  en: string
}

export interface LlmModel {
  id: string
  name: string
  enabled: boolean
  context_window: number | null
  max_output_tokens: number | null
  source: 'discovered' | 'manual'
}

export interface LlmProvider {
  id: string
  name: string
  protocol: 'openai_compatible' | 'anthropic'
  base_url: string
  /** 只有末四位。明文与密文都不会经过网络回传。 */
  key_last4: string
  has_key: boolean
  default_model: string
  /** 启用中的模型 id（兼容旧选择器） */
  models: string[]
  /** 完整模型目录（启停 / 上下文 / 来源） */
  model_catalog: LlmModel[]
  models_synced_at: string
  proxy_url: string
  is_active: boolean
  is_default: boolean
  validated_at: string
  note: string
}
