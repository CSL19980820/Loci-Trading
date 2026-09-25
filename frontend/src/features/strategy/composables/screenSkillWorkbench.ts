import type {
  ScreenSkillCatalogSnippet,
  ScreenSkillDialect,
  ScreenSkillRuntime,
} from '@/shared/types/quant'

import {
  createEmptyScreenSkillDraft,
  isUsedReferenceRow,
  paramRowsFromManifest,
  type ScreenSkillDraftModel,
} from './screenSkillDraft'

export const SCREEN_RUNTIME_OPTIONS = [
  { label: '公式', value: 'formula' },
  { label: 'Python', value: 'python' },
]

export const SCREEN_FALLBACK_FIELDS = [
  { label: '开盘价 · open', value: 'open' },
  { label: '最高价 · high', value: 'high' },
  { label: '最低价 · low', value: 'low' },
  { label: '收盘价 · close', value: 'close' },
  { label: '成交量 · volume', value: 'volume' },
  { label: '成交额 · amount', value: 'amount' },
  { label: '换手率 · turnover', value: 'turnover' },
]

export function activeScreenSkillSource(draft: ScreenSkillDraftModel): string {
  return draft.runtime === 'python' ? draft.code : draft.formula
}

/** 去掉注释与空白后的执行源指纹：公式注释写在 `{}` 里，Python 注释是 `#`（花括号是字典，不能删） */
function bodySignature(source: string, runtime: ScreenSkillRuntime): string {
  const stripped = runtime === 'python'
    ? source.replace(/#.*$/gm, '')
    : source.replace(/\{[^}]*\}/g, '')
  return stripped.replace(/\s+/g, '')
}

function logicSignature(rows: ScreenSkillDraftModel['logic']): string {
  return rows
    .map((row) => [row.title, row.expression, row.explanation, row.citationsText].map((v) => v.trim()).join('|'))
    .filter((line) => line !== '|||')
    .join('\n')
}

function paramSignature(rows: ScreenSkillDraftModel['params']): string {
  return rows
    .filter((row) => row.key.trim())
    .map((row) => [row.key, row.type, row.defaultValue, row.min, row.max, row.label].map((v) => String(v).trim()).join('|'))
    .join('\n')
}

/**
 * 草稿还是起手状态：执行源、策略脉络、参数都与模板一致，说明与资料为空。
 * 这时 AI 生成即新建；用户动过任何一处，都按「改写」把现有内容带给模型。
 */
export function isPristineScreenSkillDraft(draft: ScreenSkillDraftModel): boolean {
  const template = createEmptyScreenSkillDraft(draft.runtime === 'python' ? 'python' : 'blank')
  const body = bodySignature(activeScreenSkillSource(draft), draft.runtime)
  if (body && body !== bodySignature(activeScreenSkillSource(template), draft.runtime)) return false
  if (draft.description.trim()) return false
  if (draft.references.some(isUsedReferenceRow)) return false
  const logic = logicSignature(draft.logic)
  if (logic && logic !== logicSignature(template.logic)) return false
  const params = paramSignature(draft.params)
  return !params || params === paramSignature(template.params)
}

export function buildAiRevisionInstruction(
  draft: ScreenSkillDraftModel,
  instruction: string,
  maxChars = 19_000,
): string {
  const request = instruction.trim()
  const logicContext = draft.logic
    .filter((item) => item.title.trim() || item.expression.trim() || item.explanation.trim())
    .map((item, index) => `${index + 1}. ${item.title || '未命名规则'}：${item.expression}；${item.explanation}`)
    .join('\n') || '未填写'
  const header = [
    '请在同一份 Screen Skill 草稿上完成以下编写或修改要求。',
    `用户要求：${request}`,
    `当前运行时：${draft.runtime}`,
    `当前方言：${draft.dialect}`,
    `当前名称：${draft.name || '未命名'}`,
    `当前说明：${draft.description || '未填写'}`,
    `入场时点：${draft.entryTiming}`,
    `数据字段：${draft.dataFields.join(', ')}`,
    '当前中文策略脉络：',
    logicContext,
    '必须返回完整草稿，保留并准确引用用户提供的资料，不得虚构来源。',
    '当前执行源：',
  ].join('\n')
  return truncateAiContext(`${header}\n${activeScreenSkillSource(draft)}`, maxChars)
}

function truncateAiContext(value: string, maxChars: number): string {
  const limit = Math.max(0, Math.trunc(maxChars))
  if (value.length <= limit) return value
  const marker = '\n…（当前草稿正文已截断）'
  if (limit <= marker.length) return marker.slice(0, limit)
  return `${value.slice(0, limit - marker.length)}${marker}`
}

export function switchScreenSkillRuntime(
  draft: ScreenSkillDraftModel,
  runtime: ScreenSkillRuntime,
): void {
  if (draft.runtime === runtime) return
  draft.runtime = runtime
  if (runtime === 'python') {
    draft.dialect = 'python'
    const template = createEmptyScreenSkillDraft('python')
    if (!draft.code.trim()) draft.code = template.code
    if (!draft.entrypoint.trim()) draft.entrypoint = template.entrypoint
    return
  }
  if (draft.dialect === 'python') draft.dialect = 'loci'
  if (!draft.formula.trim()) draft.formula = createEmptyScreenSkillDraft().formula
}

export function applyCatalogSnippet(
  draft: ScreenSkillDraftModel,
  snippet: ScreenSkillCatalogSnippet,
): void {
  switchScreenSkillRuntime(draft, snippet.runtime)
  draft.dialect = snippet.dialect
  if (snippet.runtime === 'python') {
    draft.code = snippet.code
    draft.entrypoint ||= 'strategy.py:compute'
  } else {
    draft.formula = snippet.code
  }
  draft.dataFields = [...new Set([...draft.dataFields, ...snippet.required_fields])]
  draft.factorsText = snippet.factors.join(', ')
  draft.params = paramRowsFromManifest(snippet.params)
}

export function applyImportedSource(
  draft: ScreenSkillDraftModel,
  payload: {
    runtime: ScreenSkillRuntime
    dialect: ScreenSkillDialect
    source: string
  },
): void {
  switchScreenSkillRuntime(draft, payload.runtime)
  draft.dialect = payload.dialect
  if (payload.runtime === 'python') {
    draft.code = payload.source
    draft.entrypoint ||= 'strategy.py:compute'
  } else {
    draft.formula = payload.source
  }
}
