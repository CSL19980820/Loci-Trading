export type JsonValue = string | number | boolean | null | unknown[] | Record<string, unknown>

export interface AkshareCatalogParameter {
  name: string
  required: boolean
  kind: string
  annotation: string | null
  has_default: boolean
  default: JsonValue | null
  sample: JsonValue | null
}

export interface AkshareCatalogCapability {
  name: string
  category: string
  provider: string
  signature: string
  summary: string
  /** 兼容旧字段；目录不再区分上桌。 */
  enabled?: boolean
  /** 来源英文 id（筛选用） */
  provider_id?: string
  /** 类目中文 */
  category_label?: string
  /** 兼容旧目录；试跑表单以 parameters 为唯一参数来源。 */
  sample_params?: Record<string, JsonValue>
  parameters: AkshareCatalogParameter[]
  execution_mode: string
  status: 'available' | 'needs_parameters'
  /** 入参中文说明，来自上游 docstring 的 :param:，可能缺项 */
  param_docs?: Record<string, string>
  /** 返回数据说明，来自上游 docstring 的 :return: */
  returns?: string
  /** 一键全测时写入的最近结果 */
  health_ok?: boolean | null
  health_error?: string | null
  health_elapsed_ms?: number | null
}

/** 数据源下挂了多少个可用接口。 */
export interface AkshareCatalogSource {
  id: string
  /** 中文展示名 */
  label?: string
  count: number
  /** @deprecated 已无上桌概念，保留兼容旧前端 */
  enabled?: number
}

export interface AkshareCatalog {
  akshare_version: string
  capabilities: AkshareCatalogCapability[]
  total?: number
  categories?: string[]
  sources?: AkshareCatalogSource[]
  batch_probe_max?: number
}

export interface AkshareVersionInfo {
  installed: string
  latest: string | null
  update_available: boolean
  pypi_url?: string
  error?: string | null
}

export interface AkshareBatchProbeItem {
  name: string
  ok: boolean
  skipped?: boolean
  error?: string | null
  elapsed_ms?: number | null
  rows?: number | null
  attempts?: number
}

export interface AkshareBatchProbeResult {
  results: AkshareBatchProbeItem[]
  ok: number
  failed: number
  skipped: number
  missing: string[]
  offset: number
  limit: number
  next_offset: number | null
  total_targets: number
  done: boolean
}

/** 出参列名的中英对照。上游多数返回中文列，英文名取自本仓归一映射，缺则留空。 */
export interface ColumnGloss {
  raw: string
  cn: string
  en: string
}

export interface AkshareCatalogProbeResult {
  elapsed_ms?: number | null
  rows?: number | null
  columns?: string[]
  columns_detail?: ColumnGloss[]
  sample?: Record<string, unknown>[]
  truncated?: boolean
  error?: string | null
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
