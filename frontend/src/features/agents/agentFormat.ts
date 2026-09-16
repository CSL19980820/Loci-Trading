export const agentMoney = (cents: number | undefined | null) => typeof cents === 'number' && Number.isFinite(cents)
  ? (cents / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'
export const agentTime = (value: string | undefined | null) => {
  if (!value) return '尚未运行'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '时间待核对' : new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date)
}
export const phaseName = (value?: string | null) => ({ review: '晚间复盘', premarket: '盘前计划', auction: '竞价研判', intraday: '盘中管理', closeout: '尾盘收敛' }[value ?? ''] ?? '工作记录')
export const actionName = (value?: string) => ({ buy: '买入', add: '加仓', sell: '卖出', reduce: '减仓', hold: '持有', watch: '观察', unwatch: '移出观察', take_profit: '止盈', stop_loss: '止损' }[value ?? ''] ?? '操作')
export const statusName = (value?: string | null) => ({ success: '已完成', running: '正在研究', failed: '运行失败', cancelled: '已取消', interrupted: '运行中断', filled: '模拟成交', recorded: '已记录', rejected: '未执行' }[value ?? ''] ?? '尚未运行')
export const requestKey = () => globalThis.crypto?.randomUUID?.() ?? `request-${Date.now()}-${Math.random().toString(36).slice(2)}`
