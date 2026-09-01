/**
 * 信号规则可调参数的**展示口径**。
 *
 * 权威口径在后端：`param_specs` 带 key / 中文名 / 上下限 / 单位 / 是否整数。
 * 这张静态表只是它缺席时的兜底（老后端、或联调期只回了 params/defaults）——
 * 键名由引擎钉死，前端不臆造。表里没有的规则（macd_golden_cross /
 * broken_limit_up）就是真的没有可调参数，界面照实说「无可调参数」。
 */
import type { SignalRule } from '@/shared/api/signalRules'

export type SignalParamMeta = {
  label: string
  unit?: string
  min: number
  max: number
}

/** 一个渲染就绪的数字格子：控件要的属性都算好，模板里不再做判断。 */
export type SignalParamField = {
  key: string
  label: string
  unit: string
  min: number
  max: number
  step: number
  precision: number
}

export const SIGNAL_PARAM_META: Record<string, Record<string, SignalParamMeta>> = {
  ma_golden_cross: {
    fast: { label: '快线', unit: '日', min: 1, max: 250 },
    slow: { label: '慢线', unit: '日', min: 2, max: 500 },
  },
  volume_breakout: {
    volume_ratio: { label: '量比', unit: '倍', min: 1, max: 20 },
    lookback: { label: '回看', unit: '根', min: 2, max: 250 },
  },
  fast_surge: {
    speed_pct: { label: '涨速', unit: '%', min: 0.1, max: 20 },
  },
  near_limit_up: {
    gap_pct: { label: '距涨停', unit: '%', min: 0.1, max: 10 },
  },
}

/** 整数键：步进 1、不留小数位。后端给了 `integer` 就以后端为准。 */
const INTEGER_KEYS = new Set(['fast', 'slow', 'lookback'])

/**
 * 规则 → 数字格子列表。
 *
 * 优先用后端 `param_specs`（顺序也听后端的，前端不必自己排）；后端没给才回退到
 * 静态表 + 当前 params 的键，登记过的键排在前面。
 */
export function toParamFields(rule: SignalRule): SignalParamField[] {
  if (rule.specs.length) {
    return rule.specs
      .filter((spec) => spec.key)
      .map((spec) => ({
        key: spec.key,
        label: spec.label || spec.key,
        unit: spec.unit,
        min: spec.min,
        max: spec.max,
        step: spec.integer ? 1 : 0.1,
        precision: spec.integer ? 0 : 1,
      }))
  }
  const meta = SIGNAL_PARAM_META[rule.id] ?? {}
  const known = Object.keys(meta).filter((key) => key in rule.params)
  const rest = Object.keys(rule.params).filter((key) => !(key in meta))
  return [...known, ...rest].map((key) => {
    const entry = meta[key]
    const integer = INTEGER_KEYS.has(key)
    return {
      key,
      label: entry?.label || key,
      unit: entry?.unit ?? '',
      min: entry?.min ?? 0,
      max: entry?.max ?? 10000,
      step: integer ? 1 : 0.1,
      precision: integer ? 0 : 1,
    }
  })
}
