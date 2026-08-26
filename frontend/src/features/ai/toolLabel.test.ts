import { describe, expect, it } from 'vitest'

import { localizeAgentLine, toolLabel } from './toolLabel'

describe('toolLabel', () => {
  it('maps known system tools to Chinese verbs', () => {
    expect(toolLabel('ledger_positions')).toBe('读取持仓')
    expect(toolLabel('market_kline')).toBe('拉取日 K')
    expect(toolLabel('ledger_record_trade')).toBe('写入成交')
    expect(toolLabel('strategy_screen')).toBe('运行筛选')
  })

  it('falls back via prefix without dumping English snake_case', () => {
    expect(toolLabel('ops_job_pause')).toBe('运维任务')
    expect(toolLabel('mcp_weather')).toBe('调用外部工具')
    expect(toolLabel('custom_foo_bar')).toBe('本机工具')
  })

  it('unwraps server__tool MCP names', () => {
    expect(toolLabel('wudao__market_kline')).toBe('拉取日 K')
  })

  it('handles empty input', () => {
    expect(toolLabel('')).toBe('未知工具')
    expect(toolLabel(null)).toBe('未知工具')
  })

  it('localizes agent timeline lines that embed tool names', () => {
    expect(localizeAgentLine('正在读取 ledger_dashboard')).toBe('正在读取账本仪表盘')
    expect(localizeAgentLine('已整理 market_kline 证据')).toBe('已整理 拉取日 K 证据')
  })
})
