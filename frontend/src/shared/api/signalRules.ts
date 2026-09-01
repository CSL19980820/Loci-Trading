/**
 * 信号规则维护接口。
 *
 * 路径以后端实现为准：`/api/market/signals/rules`（联调初稿写的 `signal-rules`
 * 已作废，两边已对齐，不留回退分支——留着只会让人以为路径还没定下来）。
 *
 * 可调参数的**权威口径来自后端** `param_specs`（键 / 中文名 / 上下限 / 单位 /
 * 是否整数）。后端没给时才退到前端那张静态表（signalRuleMeta.ts）。
 */
import { quantRequest } from '@/shared/api/quant_client'

/** 参数值一律是数值；键名由引擎钉死，前端不臆造。 */
export type SignalRuleParams = Record<string, number>

export type SignalParamSpec = {
  key: string
  label: string
  default: number
  min: number
  max: number
  unit: string
  integer: boolean
}

export type SignalRule = {
  id: string
  label: string
  description: string
  enabled: boolean
  /** 当前生效值 = 默认值 + 覆盖值 */
  params: SignalRuleParams
  defaults: SignalRuleParams
  /** 被改过的键；空表示这条规则整条都还是默认值 */
  overrides: SignalRuleParams
  specs: SignalParamSpec[]
  repeatable: boolean
  minBars: number
}

export type SignalRulePatch = {
  enabled?: boolean
  params?: SignalRuleParams
}

type RawParamSpec = {
  key?: string
  label?: string
  default?: number
  min?: number
  max?: number
  unit?: string
  integer?: boolean
}

type RawSignalRule = {
  rule_id?: string
  id?: string
  label?: string
  description?: string
  enabled?: boolean
  params?: Record<string, unknown>
  defaults?: Record<string, unknown>
  overrides?: Record<string, unknown>
  param_specs?: RawParamSpec[]
  repeatable?: boolean
  min_bars?: number
  minBars?: number
}

type RawRulesPayload = { rules?: RawSignalRule[] }

const RULES_PATH = '/market/signals/rules'

function parseParams(raw: Record<string, unknown> | undefined): SignalRuleParams {
  const out: SignalRuleParams = {}
  if (!raw || typeof raw !== 'object') return out
  for (const [key, value] of Object.entries(raw)) {
    const num = Number(value)
    if (Number.isFinite(num)) out[key] = num
  }
  return out
}

export function parseSignalRule(raw: RawSignalRule): SignalRule {
  const defaults = parseParams(raw.defaults)
  const params = parseParams(raw.params)
  const specs = Array.isArray(raw.param_specs) ? raw.param_specs : []
  return {
    id: String(raw.rule_id ?? raw.id ?? ''),
    label: String(raw.label ?? raw.rule_id ?? raw.id ?? ''),
    description: String(raw.description ?? ''),
    // 库里没有这条记录 = 从没改过 = 启用；后端也是这个口径
    enabled: raw.enabled === undefined ? true : Boolean(raw.enabled),
    // 后端可能只回 defaults（规则从未被改过），两边取并集，界面才有格子可填
    params: { ...defaults, ...params },
    defaults,
    overrides: parseParams(raw.overrides),
    specs: specs.map((spec) => ({
      key: String(spec.key ?? ''),
      label: String(spec.label ?? spec.key ?? ''),
      default: Number(spec.default ?? 0),
      min: Number(spec.min ?? 0),
      max: Number(spec.max ?? 0),
      unit: String(spec.unit ?? ''),
      integer: Boolean(spec.integer),
    })),
    repeatable: Boolean(raw.repeatable),
    minBars: Number(raw.min_bars ?? raw.minBars ?? 0),
  }
}

export async function getSignalRules(): Promise<SignalRule[]> {
  const raw = await quantRequest<RawSignalRule[] | RawRulesPayload | null>(RULES_PATH)
  const list = Array.isArray(raw) ? raw : Array.isArray(raw?.rules) ? raw.rules : []
  return list.map(parseSignalRule)
}

/**
 * 局部更新，返回**服务端最终生效值**（越界会被 400 挡回，跨参数冲突也是），
 * 界面据此回写，免得屏幕上是用户输入、库里却是另一个数。后端不回规则体则 null。
 */
export async function updateSignalRule(
  ruleId: string,
  patch: SignalRulePatch,
): Promise<SignalRule | null> {
  const suffix = `/${encodeURIComponent(ruleId)}`
  const init: RequestInit = { method: 'PUT', body: JSON.stringify(patch) }
  const raw = await quantRequest<RawSignalRule | null>(`${RULES_PATH}${suffix}`, init)
  if (!raw || typeof raw !== 'object') return null
  if (!raw.rule_id && !raw.id) return null
  return parseSignalRule(raw)
}
