/**
 * Human-readable labels for system / MCP tool names shown in the assistant UI.
 *
 * 注意：`ledger_*` 里的持仓/成交类工具已随 2026-08 持仓下线在后端删除，但这里的映射
 * **保留不删**——它只用于渲染**历史**会话的工具回执。删了映射，旧回执会从「读取持仓」
 * 退化成 `ledger_positions`，把已经发生过的事显示得更难懂。清理时勿当漏网一并删。
 */

const TOOL_LABELS: Record<string, string> = {
  ledger_dashboard: '读取账本仪表盘',
  ledger_positions: '读取持仓',
  ledger_trades: '查询成交',
  ledger_record_trade: '写入成交',
  ledger_adjust_positions: '批量调整持仓',
  ledger_record_cashflow: '记录出入金',
  ledger_record_daily_pnl: '写入当日盈亏',
  ledger_record_snapshot: '记录资产快照',
  ledger_upsert_candidate: '更新候选裁决',
  ledger_delete_candidate: '删除候选',
  ledger_delete_candidate_pool: '清空候选池',
  ledger_record_plan: '写入交易预案',
  ledger_record_review: '写入复盘',
  qianlong_candidate_pool: '读取潜龙候选池',
  qianlong_pool_evidence: '读取潜龙池证据',
  qianlong_commit: '提交潜龙裁决',
  strategy_catalog: '读取策略目录',
  strategy_screen: '运行筛选',
  system_tool_catalog: '读取工具目录',
  market_kline: '拉取日 K',
  market_search: '搜索标的',
  research_catalog: '读取研究目录',
  research_profile: '读取研究画像',
  ops_provider_catalog: '读取模型供应商',
  ops_set_default_provider: '设置默认供应商',
  ops_set_default_model: '设置默认模型',
  ops_update_provider: '更新供应商',
  ops_delete_provider: '删除供应商',
  ops_jobs_list: '读取运维任务',
  ops_job_create: '创建运维任务',
  ops_job_update: '更新运维任务',
  ops_job_delete: '删除运维任务',
  ops_job_trigger: '触发运维任务',
  web_search: '网页检索',
  web_fetch: '抓取网页',
  memory_update: '更新记忆',
}

const PREFIX_LABELS: Array<[prefix: string, label: string]> = [
  ['ledger_update_', '更新账本'],
  ['ledger_record_', '写入账本'],
  ['ledger_delete_', '删除账本项'],
  ['ops_job_', '运维任务'],
  ['ops_', '运维操作'],
  ['market_', '行情查询'],
  ['qianlong_', '潜龙工具'],
  ['strategy_', '策略工具'],
  ['research_', '研究工具'],
  ['memory_', '记忆工具'],
  ['web_', '外网检索'],
  ['mcp_', '调用外部工具'],
]

/** Map a tool `name` to a short Chinese verb phrase for the receipt rail / sidebar. */
export function toolLabel(name: string | undefined | null): string {
  const raw = String(name ?? '').trim()
  if (!raw) return '未知工具'
  if (TOOL_LABELS[raw]) return TOOL_LABELS[raw]
  for (const [prefix, label] of PREFIX_LABELS) {
    if (raw.startsWith(prefix)) return label
  }
  if (raw.includes('__')) {
    const leaf = raw.split('__').pop() || raw
    if (leaf !== raw) return toolLabel(leaf)
  }
  return '本机工具'
}

/**
 * 把过程行里夹带的英文工具名换成中文（兼容旧会话 timeline）。
 * 例：`正在读取 ledger_dashboard` → `正在读取账本仪表盘`
 */
export function localizeAgentLine(text: string | undefined | null): string {
  const raw = String(text ?? '').trim()
  if (!raw) return ''
  const reading = raw.match(/^正在读取\s+([a-z][\w]*(?:__[\w]+)?)$/i)
  if (reading) return `正在${toolLabel(reading[1])}`
  return raw.replace(/\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b/gi, (match) => {
    const zh = toolLabel(match)
    return zh === '本机工具' || zh === '未知工具' ? match : zh
  })
}
