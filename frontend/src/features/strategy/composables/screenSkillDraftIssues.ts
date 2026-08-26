/** 策稿校验错误 → 顶层 Tab + 表单字段，供跳转与标红。 */

export type WorkbenchPane = 'formula' | 'strategy' | 'data' | 'params' | 'references'

export type DraftIssue = {
  message: string
  tab: WorkbenchPane
  field: string
}

function logicField(message: string, part: string): string {
  const byIndex = message.match(/逻辑 #(\d+)/)
  if (byIndex) return `logic.${Number(byIndex[1]) - 1}.${part}`
  const byId = message.match(/逻辑 ([^\s#]+)/)
  if (byId) return `logic.id.${byId[1]}.${part}`
  return `logic.${part}`
}

function referenceField(message: string, part: string): string {
  const byIndex = message.match(/资料来源 #(\d+)/)
  if (byIndex) return `references.${Number(byIndex[1]) - 1}.${part}`
  const byId = message.match(/资料来源 ([^\s#]+)/)
  if (byId) return `references.id.${byId[1]}.${part}`
  return `references.${part}`
}

export function classifyDraftError(message: string): Omit<DraftIssue, 'message'> {
  if (/公式正文|脚本代码|Python 代码/.test(message)) return { tab: 'formula', field: 'source' }
  if (/Slug|标识/.test(message)) return { tab: 'strategy', field: 'slug' }
  if (/名称不能/.test(message)) return { tab: 'strategy', field: 'name' }
  if (/说明不能/.test(message)) return { tab: 'strategy', field: 'description' }
  if (/信号名/.test(message)) return { tab: 'strategy', field: 'signal' }
  if (/最少 K 线/.test(message)) return { tab: 'strategy', field: 'minBars' }
  if (/因子名/.test(message)) return { tab: 'strategy', field: 'factorsText' }
  if (/逻辑/.test(message)) {
    if (/缺少编号|缺少 ID/.test(message)) return { tab: 'strategy', field: logicField(message, 'id') }
    if (message.includes('缺少标题')) return { tab: 'strategy', field: logicField(message, 'title') }
    if (message.includes('缺少表达式')) return { tab: 'strategy', field: logicField(message, 'expression') }
    if (message.includes('缺少解释')) return { tab: 'strategy', field: logicField(message, 'explanation') }
    if (message.includes('引用了不存在')) return { tab: 'strategy', field: logicField(message, 'citationsText') }
    return { tab: 'strategy', field: 'logic' }
  }
  if (/资料来源|可追溯资料/.test(message)) {
    if (/缺少编号|缺少 ID/.test(message)) return { tab: 'references', field: referenceField(message, 'id') }
    if (message.includes('缺少标题')) return { tab: 'references', field: referenceField(message, 'title') }
    if (message.includes('缺少类型')) return { tab: 'references', field: referenceField(message, 'kind') }
    if (message.includes('至少填写')) return { tab: 'references', field: referenceField(message, 'locator') }
    return { tab: 'references', field: 'references' }
  }
  if (/数据字段/.test(message)) return { tab: 'data', field: 'dataFields' }
  if (/上市天数/.test(message)) return { tab: 'data', field: 'minListDays' }
  if (/入口函数/.test(message)) return { tab: 'params', field: 'entrypoint' }
  if (/参数|方言|运行时/.test(message)) return { tab: 'params', field: 'params' }
  return { tab: 'strategy', field: 'general' }
}

export function issuesFromMessages(errors: string[]): DraftIssue[] {
  return errors.map((message) => ({ message, ...classifyDraftError(message) }))
}

/** 跳到第一条报错所在 Tab（与校验输出顺序一致）。 */
export function firstIssueTab(issues: DraftIssue[]): WorkbenchPane {
  return issues[0]?.tab ?? 'strategy'
}

export function fieldErrorMap(issues: DraftIssue[]): Record<string, string> {
  const map: Record<string, string> = {}
  for (const issue of issues) {
    if (!map[issue.field]) map[issue.field] = issue.message
  }
  return map
}

export function tabIssueCounts(issues: DraftIssue[]): Partial<Record<WorkbenchPane, number>> {
  const counts: Partial<Record<WorkbenchPane, number>> = {}
  for (const issue of issues) {
    counts[issue.tab] = (counts[issue.tab] ?? 0) + 1
  }
  return counts
}

/** 逻辑/资料行上解析 fieldErrors 键（支持 index 与 id 两种）。 */
export function rowFieldError(
  fieldErrors: Record<string, string>,
  kind: 'logic' | 'references',
  index: number,
  id: string,
  part: string,
): string {
  return (
    fieldErrors[`${kind}.${index}.${part}`]
    || fieldErrors[`${kind}.id.${id}.${part}`]
    || ''
  )
}
