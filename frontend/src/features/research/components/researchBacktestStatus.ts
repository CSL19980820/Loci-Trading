/**
 * 研究回测的状态文案与色档。
 *
 * run、job、工作流三处状态共用同一套词表与 tag 类型，摊在面板里就会随手写成三份。
 * 纯函数一份，谁渲染谁调用。
 */
export function statusType(status: string): 'success' | 'warning' | 'info' | 'danger' {
  if (status === 'completed') return 'success'
  if (status === 'stale' || status === 'awaiting_human_review') return 'warning'
  if (status === 'failed' || status === 'rejected') return 'danger'
  return 'info'
}

export function statusLabel(status: string): string {
  return ({
    queued: '排队中', waiting: '等待中', running: '运行中', awaiting_human_review: '待人工签署', completed: '已完成', stale: '已过期', failed: '失败', rejected: '已拒绝',
  })[status] || status
}

export function stageType(status: string): 'success' | 'warning' | 'info' | 'danger' {
  if (status === 'completed') return 'success'
  if (status === 'failed' || status === 'blocked') return 'danger'
  if (status === 'running' || status === 'waiting') return 'warning'
  return 'info'
}
