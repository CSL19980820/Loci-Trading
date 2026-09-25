import type {
  BoardBucket,
  EntryTiming,
  ScreenSkillAdjust,
  ScreenSkillDetail,
  ScreenSkillGenerateResponse,
  ScreenSkillLogic,
  ScreenSkillManifest,
  ScreenSkillParamDef,
  ScreenSkillParamType,
  ScreenSkillReference,
  ScreenSkillRuntime,
  ScreenSkillUpsertPayload,
  UniverseSpec,
} from '@/shared/types/quant'
export type ScreenSkillDraftSource = 'blank' | 'description' | 'tdx' | 'ths' | 'python'
export interface ScreenSkillParamRow {
  key: string
  type: ScreenSkillParamType
  defaultValue: string
  min: string
  max: string
  label: string
}
export interface ScreenSkillLogicRow {
  id: string
  title: string
  expression: string
  explanation: string
  citationsText: string
}
export interface ScreenSkillReferenceRow {
  id: string
  title: string
  kind: string
  url: string
  path: string
  section: string
  quote: string
}
export interface ScreenSkillDraftModel {
  slug: string
  name: string
  description: string
  version: string
  enabled: boolean
  runtime: ScreenSkillRuntime
  dialect: 'loci' | 'tdx' | 'ths' | 'python'
  formula: string
  code: string
  entrypoint: string
  entryTiming: EntryTiming
  minBars: number
  signal: string
  factorsText: string
  params: ScreenSkillParamRow[]
  logic: ScreenSkillLogicRow[]
  references: ScreenSkillReferenceRow[]
  dataFields: string[]
  adjust: ScreenSkillAdjust
  universePreset: string
  boards: BoardBucket[]
  excludeSt: boolean
  excludeDelisting: boolean
  excludeSuspended: boolean
  minListDays: number | null
  codesIncludeText: string
  codesExcludeText: string
  industriesIncludeText: string
  industriesExcludeText: string
  packageRevision: string
  strategyRevision: string
}
const DEFAULT_FIELDS = ['open', 'high', 'low', 'close', 'volume', 'amount']
let rowSeed = 0
function nextRowId(prefix: string): string {
  rowSeed += 1
  return `${prefix}_${rowSeed}`
}
export function blankParamRow(): ScreenSkillParamRow {
  return { key: '', type: 'int', defaultValue: '', min: '', max: '', label: '' }
}
export function blankLogicRow(): ScreenSkillLogicRow {
  return { id: nextRowId('logic'), title: '', expression: '', explanation: '', citationsText: '' }
}
export function blankReferenceRow(): ScreenSkillReferenceRow {
  return { id: nextRowId('ref'), title: '', kind: 'note', url: '', path: '', section: '', quote: '' }
}
export function isCurrentSkillLoad(
  token: number,
  latestToken: number,
  requestedSlug: string,
  currentRouteSlug: string,
): boolean {
  return token === latestToken && requestedSlug === currentRouteSlug
}
function starterFormula(source: ScreenSkillDraftSource): string {
  if (source === 'tdx') {
    return '{通达信草稿}\nBASE_MA:=MA(CLOSE,N);\nPICK: CLOSE>BASE_MA;'
  }
  if (source === 'ths') {
    return '{同花顺草稿}\nBASE_MA:=MA(CLOSE,N);\nPICK: CLOSE>BASE_MA;'
  }
  return '{Loci 公式草稿}\nBASE_MA:=MA(CLOSE,N);\nPICK: CLOSE>BASE_MA;'
}
function starterCode(): string {
  return [
    'def compute(panels, params):',
    '    lookback = int(params.get("LOOKBACK", 20))',
    '    close = panels["close"]',
    '    base_ma = close.rolling(lookback).mean()',
    '    signal = close > base_ma',
    '    return {',
    '        "signals": signal,',
    '        "factors": {"BASE_MA": base_ma},',
    '    }',
  ].join('\n')
}
function defaultBoards(): BoardBucket[] {
  return ['main', 'chi_next', 'star']
}
function defaultLogicRows(): ScreenSkillLogicRow[] {
  return [
    {
      id: nextRowId('logic'),
      title: '核心触发',
      expression: 'CLOSE > BASE_MA',
      explanation: '价格重新站上基准均线时触发初筛。',
      citationsText: '',
    },
  ]
}
export function createEmptyScreenSkillDraft(source: ScreenSkillDraftSource = 'blank'): ScreenSkillDraftModel {
  const runtime: ScreenSkillRuntime = source === 'python' ? 'python' : 'formula'
  const dialect =
    source === 'tdx' ? 'tdx' : source === 'ths' ? 'ths' : source === 'python' ? 'python' : 'loci'
  return {
    slug: '',
    name: source === 'description' ? 'AI 草稿战法' : source === 'python' ? 'Python 草稿战法' : '',
    description: '',
    version: '0.1.0',
    enabled: true,
    runtime,
    dialect,
    formula: runtime === 'formula' ? starterFormula(source) : '',
    code: runtime === 'python' ? starterCode() : '',
    entrypoint: 'strategy.py:compute',
    entryTiming: 'next_open',
    minBars: 120,
    signal: 'PICK',
    factorsText: 'BASE_MA',
    params: [
      {
        key: runtime === 'python' ? 'LOOKBACK' : 'N',
        type: 'int',
        defaultValue: '20',
        min: '5',
        max: '120',
        label: runtime === 'python' ? '回看周期' : '均线周期',
      },
    ],
    logic: defaultLogicRows(),
    references: [blankReferenceRow()],
    dataFields: [...DEFAULT_FIELDS],
    adjust: 'qfq',
    universePreset: '',
    boards: defaultBoards(),
    excludeSt: true,
    excludeDelisting: true,
    excludeSuspended: false,
    minListDays: 60,
    codesIncludeText: '',
    codesExcludeText: '',
    industriesIncludeText: '',
    industriesExcludeText: '',
    packageRevision: '',
    strategyRevision: '',
  }
}
function formatParamValue(type: ScreenSkillParamType, value: number | boolean | undefined): string {
  if (value === undefined) return ''
  if (type === 'bool') return String(Boolean(value))
  return String(value)
}
function formatListText(values: string[] | null | undefined): string {
  return (values ?? []).join('\n')
}
export function parseListText(raw: string): string[] {
  const seen = new Set<string>()
  const items: string[] = []
  for (const value of raw.split(/[\n,，;\s]+/)) {
    const next = value.trim()
    if (!next || seen.has(next)) continue
    seen.add(next)
    items.push(next)
  }
  return items
}
function hasAnyText(values: string[]): boolean {
  return values.some((value) => value.trim())
}
/** 仅 id 预填不算已用；用户动过正文才纳入校验。 */
function isUsedLogicRow(row: ScreenSkillLogicRow): boolean {
  return hasAnyText([row.title, row.expression, row.explanation, row.citationsText])
}
/** 编号/类型有默认值；只有填了标题或定位信息才算要保存的资料。 */
export function isUsedReferenceRow(row: ScreenSkillReferenceRow): boolean {
  return hasAnyText([row.title, row.url, row.path, row.section, row.quote])
}
export function paramRowsFromManifest(
  params: Record<string, ScreenSkillParamDef> | undefined,
): ScreenSkillParamRow[] {
  const entries = Object.entries(params ?? {})
  if (!entries.length) return [blankParamRow()]
  return entries.map(([key, def]) => ({
    key,
    type: def.type,
    defaultValue: formatParamValue(def.type, def.default),
    min: def.type === 'bool' ? '' : formatParamValue(def.type, def.min),
    max: def.type === 'bool' ? '' : formatParamValue(def.type, def.max),
    label: def.label ?? '',
  }))
}
function logicRowsFromManifest(logic: ScreenSkillLogic[] | null | undefined): ScreenSkillLogicRow[] {
  if (!logic?.length) return [blankLogicRow()]
  return logic.map((item) => ({
    id: item.id,
    title: item.title,
    expression: item.expression,
    explanation: item.explanation,
    citationsText: item.citations.join(', '),
  }))
}
function referenceRowsFromManifest(references: ScreenSkillReference[] | null | undefined): ScreenSkillReferenceRow[] {
  if (!references?.length) return [blankReferenceRow()]
  return references.map((item) => ({
    id: item.id,
    title: item.title,
    kind: item.kind,
    url: item.url ?? '',
    path: item.path ?? '',
    section: item.section ?? '',
    quote: item.quote ?? '',
  }))
}
function dataDraftFromManifest(manifest: ScreenSkillManifest | undefined) {
  const data = manifest?.data
  const universe = data?.universe
  return {
    dataFields: data?.fields?.length ? [...data.fields] : [...DEFAULT_FIELDS],
    adjust: data?.adjust ?? 'qfq',
    universePreset: universe?.preset ?? '',
    boards: universe?.boards?.length ? [...universe.boards] : defaultBoards(),
    excludeSt: universe?.exclude_st ?? true,
    excludeDelisting: universe?.exclude_delisting ?? true,
    excludeSuspended: universe?.exclude_suspended ?? false,
    minListDays: universe?.min_list_days ?? 60,
    codesIncludeText: formatListText(universe?.codes_include),
    codesExcludeText: formatListText(universe?.codes_exclude),
    industriesIncludeText: formatListText(universe?.industries_include),
    industriesExcludeText: formatListText(universe?.industries_exclude),
  }
}
export function draftFromScreenSkill(detail: ScreenSkillDetail): ScreenSkillDraftModel {
  const runtime: ScreenSkillRuntime = detail.runtime ?? (detail.code ? 'python' : 'formula')
  const dataDraft = dataDraftFromManifest(detail.manifest)
  return {
    slug: detail.slug,
    name: detail.name,
    description: detail.description,
    version: detail.version ?? '0.1.0',
    enabled: detail.enabled !== false,
    runtime,
    dialect: detail.dialect ?? (runtime === 'python' ? 'python' : 'loci'),
    formula: detail.formula ?? '',
    code: detail.code ?? '',
    entrypoint: detail.entrypoint ?? 'strategy.py:compute',
    entryTiming: detail.manifest.entry_timing,
    minBars: detail.manifest.min_bars,
    signal: detail.manifest.output.signal,
    factorsText: detail.manifest.factors.join(', '),
    params: paramRowsFromManifest(detail.manifest.params),
    logic: logicRowsFromManifest(detail.manifest.logic),
    references: referenceRowsFromManifest(detail.manifest.references),
    ...dataDraft,
    packageRevision: detail.package_revision,
    strategyRevision: detail.strategy_revision,
  }
}
export function draftFromGeneratedSkill(
  response: ScreenSkillGenerateResponse,
  base: ScreenSkillDraftModel,
): ScreenSkillDraftModel {
  const next = response.draft
  if (!next) return base
  const manifest = next.manifest
  const dataDraft = manifest ? dataDraftFromManifest(manifest) : null
  const runtime: ScreenSkillRuntime = next.runtime ?? base.runtime
  return {
    slug: next.slug ?? base.slug,
    name: next.name ?? base.name,
    description: next.description ?? base.description,
    version: next.version ?? base.version,
    enabled: next.enabled ?? base.enabled,
    runtime,
    dialect: next.dialect ?? base.dialect,
    formula: next.formula ?? base.formula,
    code: next.code ?? base.code,
    entrypoint: next.entrypoint ?? base.entrypoint,
    entryTiming: manifest?.entry_timing ?? base.entryTiming,
    minBars: manifest?.min_bars ?? base.minBars,
    signal: manifest?.output?.signal ?? base.signal,
    factorsText: manifest?.factors?.join(', ') ?? base.factorsText,
    params: manifest?.params ? paramRowsFromManifest(manifest.params) : base.params,
    logic: manifest ? logicRowsFromManifest(manifest.logic) : base.logic,
    references: manifest ? referenceRowsFromManifest(manifest.references) : base.references,
    dataFields: dataDraft?.dataFields ?? [...base.dataFields],
    adjust: dataDraft?.adjust ?? base.adjust,
    universePreset: dataDraft?.universePreset ?? base.universePreset,
    boards: dataDraft?.boards ?? [...base.boards],
    excludeSt: dataDraft?.excludeSt ?? base.excludeSt,
    excludeDelisting: dataDraft?.excludeDelisting ?? base.excludeDelisting,
    excludeSuspended: dataDraft?.excludeSuspended ?? base.excludeSuspended,
    minListDays: dataDraft?.minListDays ?? base.minListDays,
    codesIncludeText: dataDraft?.codesIncludeText ?? base.codesIncludeText,
    codesExcludeText: dataDraft?.codesExcludeText ?? base.codesExcludeText,
    industriesIncludeText: dataDraft?.industriesIncludeText ?? base.industriesIncludeText,
    industriesExcludeText: dataDraft?.industriesExcludeText ?? base.industriesExcludeText,
    packageRevision: base.packageRevision,
    strategyRevision: response.strategy_revision ?? base.strategyRevision,
  }
}
function parseNumber(raw: string, label: string): number {
  const text = raw.trim()
  const value = Number(text)
  if (!text || !Number.isFinite(value)) {
    throw new Error(`${label} 必须是数字`)
  }
  return value
}
function parseInteger(raw: string, label: string): number {
  const text = raw.trim()
  if (!/^-?\d+$/.test(text)) {
    throw new Error(`${label} 必须是整数`)
  }
  const value = Number(text)
  if (!Number.isSafeInteger(value)) {
    throw new Error(`${label} 超出整数范围`)
  }
  return value
}
function parseParamRow(row: ScreenSkillParamRow): ScreenSkillParamDef {
  if (!row.key.trim()) throw new Error('参数名不能为空')
  if (row.type === 'bool') {
    const text = row.defaultValue.trim().toLowerCase()
    const truthy = new Set(['true', '1', '是', '开', '真'])
    const falsy = new Set(['false', '0', '否', '关', '假'])
    if (!truthy.has(text) && !falsy.has(text)) {
      throw new Error(`参数 ${row.key} 的默认值必须是 是 或 否`)
    }
    return {
      type: 'bool',
      default: truthy.has(text),
      ...(row.label.trim() ? { label: row.label.trim() } : {}),
    }
  }
  const parseValue = row.type === 'int' ? parseInteger : parseNumber
  const min = parseValue(row.min, `参数 ${row.key} 的最小值`)
  const max = parseValue(row.max, `参数 ${row.key} 的最大值`)
  const value = parseValue(row.defaultValue, `参数 ${row.key} 的默认值`)
  if (min > max) {
    throw new Error(`参数 ${row.key} 的最小值不能大于最大值`)
  }
  if (value < min || value > max) {
    throw new Error(`参数 ${row.key} 的默认值必须落在最小值与最大值之间`)
  }
  return {
    type: row.type,
    default: value,
    min,
    max,
      ...(row.label.trim() ? { label: row.label.trim() } : {}),
  }
}
function buildReferenceRows(
  rows: ScreenSkillReferenceRow[],
): { references: ScreenSkillReference[]; errors: string[]; ids: Set<string> } {
  const errors: string[] = []
  const references: ScreenSkillReference[] = []
  const ids = new Set<string>()
  for (const [index, row] of rows.entries()) {
    if (!isUsedReferenceRow(row)) continue
    const id = row.id.trim()
    if (!id) {
      errors.push(`资料来源 #${index + 1} 缺少编号（填了内容就需要编号）`)
      continue
    }
    if (ids.has(id)) {
      errors.push(`资料来源 ${id} 重复`)
      continue
    }
    if (!row.title.trim()) {
      errors.push(`资料来源 ${id} 缺少标题`)
      continue
    }
    if (!row.kind.trim()) {
      errors.push(`资料来源 ${id} 缺少类型`)
      continue
    }
    if (!hasAnyText([row.url, row.path, row.section, row.quote])) {
      errors.push(`资料来源 ${id} 至少填写链接、路径、章节或引文之一`)
      continue
    }
    ids.add(id)
    references.push({
      id,
      title: row.title.trim(),
      kind: row.kind.trim(),
      ...(row.url.trim() ? { url: row.url.trim() } : {}),
      ...(row.path.trim() ? { path: row.path.trim() } : {}),
      ...(row.section.trim() ? { section: row.section.trim() } : {}),
      ...(row.quote.trim() ? { quote: row.quote.trim() } : {}),
    })
  }
  return { references, errors, ids }
}
function buildLogicRows(rows: ScreenSkillLogicRow[], referenceIds: Set<string>): { logic: ScreenSkillLogic[]; errors: string[] } {
  const errors: string[] = []
  const logic: ScreenSkillLogic[] = []
  const ids = new Set<string>()
  for (const [index, row] of rows.entries()) {
    if (!isUsedLogicRow(row)) continue
    const id = row.id.trim()
    if (!id) {
      errors.push(`逻辑 #${index + 1} 缺少编号`)
      continue
    }
    if (ids.has(id)) {
      errors.push(`逻辑 ${id} 重复`)
      continue
    }
    if (!row.title.trim()) {
      errors.push(`逻辑 ${id} 缺少标题`)
      continue
    }
    if (!row.expression.trim()) {
      errors.push(`逻辑 ${id} 缺少表达式`)
      continue
    }
    if (!row.explanation.trim()) {
      errors.push(`逻辑 ${id} 缺少解释`)
      continue
    }
    const citations = parseListText(row.citationsText)
    const missing = citations.filter((citation) => !referenceIds.has(citation))
    if (missing.length) {
      errors.push(`逻辑 ${id} 引用了不存在的资料：${missing.join(', ')}`)
      continue
    }
    ids.add(id)
    logic.push({
      id,
      title: row.title.trim(),
      expression: row.expression.trim(),
      explanation: row.explanation.trim(),
      citations,
    })
  }
  return { logic, errors }
}
export function buildUniverseSpec(draft: ScreenSkillDraftModel): UniverseSpec {
  const minListDays = draft.minListDays == null || Number.isNaN(draft.minListDays) ? null : Math.max(0, Math.trunc(draft.minListDays))
  return {
    preset: draft.universePreset.trim() || null,
    boards: draft.boards.length ? [...new Set(draft.boards)] : null,
    exclude_st: draft.excludeSt,
    exclude_delisting: draft.excludeDelisting,
    exclude_suspended: draft.excludeSuspended,
    min_list_days: minListDays,
    codes_include: parseListText(draft.codesIncludeText),
    codes_exclude: parseListText(draft.codesExcludeText),
    industries_include: parseListText(draft.industriesIncludeText),
    industries_exclude: parseListText(draft.industriesExcludeText),
  }
}
export function buildScreenSkillReferences(
  draft: ScreenSkillDraftModel,
): { references: ScreenSkillReference[]; errors: string[] } {
  const built = buildReferenceRows(draft.references)
  return { references: built.references, errors: built.errors }
}
export function buildScreenSkillPayload(
  draft: ScreenSkillDraftModel,
): { payload: ScreenSkillUpsertPayload | null; errors: string[] } {
  const errors: string[] = []
  const params: Record<string, ScreenSkillParamDef> = {}
  const rows = draft.params.filter((row) => row.key.trim())
  const seen = new Set<string>()
  for (const row of rows) {
    const key = row.key.trim().toUpperCase()
    if (seen.has(key)) {
      errors.push(`参数 ${key} 重复`)
      continue
    }
    seen.add(key)
    try {
      params[key] = parseParamRow({ ...row, key })
    } catch (caught: unknown) {
      errors.push(caught instanceof Error ? caught.message : `参数 ${key} 不合法`)
    }
  }
  const builtReferences = buildReferenceRows(draft.references)
  errors.push(...builtReferences.errors)
  const builtLogic = buildLogicRows(draft.logic, builtReferences.ids)
  errors.push(...builtLogic.errors)
  if (!draft.slug.trim()) errors.push('标识不能为空')
  if (!draft.name.trim()) errors.push('名称不能为空')
  if (!draft.description.trim()) errors.push('说明不能为空')
  if (!draft.signal.trim()) errors.push('信号名不能为空')
  if (!Number.isFinite(draft.minBars) || draft.minBars <= 0) errors.push('最少 K 线必须大于 0')
  if (draft.minListDays != null && (!Number.isFinite(draft.minListDays) || draft.minListDays < 0)) {
    errors.push('上市天数不能小于 0')
  }

  const fields = draft.dataFields.map((item) => item.trim()).filter(Boolean)
  if (!fields.length) errors.push('至少选择一个数据字段')
  if (draft.runtime === 'formula') {
    if (!draft.formula.trim()) errors.push('公式正文不能为空')
    if (draft.dialect === 'python') errors.push('公式运行时不能使用脚本方言')
  } else {
    if (!draft.code.trim()) errors.push('脚本代码不能为空')
    if (!draft.entrypoint.trim()) errors.push('脚本入口函数不能为空')
    if (draft.dialect !== 'python') errors.push('脚本运行时的方言必须为脚本')
  }
  const manifest: ScreenSkillManifest = {
    schema_version: 2,
    entry_timing: draft.entryTiming,
    min_bars: Math.trunc(draft.minBars),
    params,
    output: { signal: draft.signal.trim().toUpperCase() },
    factors: draft.factorsText
      .split(/[\n,]/)
      .map((item) => item.trim())
      .filter(Boolean),
    logic: builtLogic.logic,
    references: builtReferences.references,
    data: {
      fields,
      adjust: draft.adjust,
      universe: buildUniverseSpec(draft),
    },
  }
  if (!manifest.factors.length) errors.push('至少填写一个因子名')
  if (errors.length) return { payload: null, errors }
  return {
    payload: {
      slug: draft.slug.trim(),
      name: draft.name.trim(),
      description: draft.description.trim(),
      version: draft.version.trim() || undefined,
      enabled: draft.enabled,
      runtime: draft.runtime,
      dialect: draft.runtime === 'formula' ? 'loci' : draft.dialect,
      formula: draft.runtime === 'formula' ? draft.formula : undefined,
      code: draft.runtime === 'python' ? draft.code : undefined,
      entrypoint: draft.runtime === 'python' ? draft.entrypoint.trim() : undefined,
      manifest,
    },
    errors: [],
  }
}
