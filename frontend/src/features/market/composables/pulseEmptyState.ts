/**
 * 首页空态文案（纯函数，可单测）。
 *
 * 从前这两条空态写死「等 15:30 定时任务」，可新用户压根没有这条任务，
 * 首屏于是在说谎。这里按真实状态分三档：不知道 / 一次都没跑过 / 有历史但今天空，
 * 只有第三档、且确实有已启用的定时选股任务时才允许提「定时」。
 */

export interface PulseEmptyInput {
  /** 选股历史总条数；null = 未读到（不要用 0 冒充「确实没有」） */
  screenHistoryTotal: number | null
  hasEnabledScreenJob: boolean
  /** 后端 next_run_at 原样字符串（ISO 或其它），无则 null */
  nextScreenRunAt: string | null
}

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

/** 时刻格式化：能解析成 Date 就压成 `MM-DD HH:mm`，解析不了原样吐回。 */
export function formatRunClock(iso: string | null): string {
  const raw = (iso || '').trim()
  if (!raw) return ''
  // Safari/部分后端给 'YYYY-MM-DD HH:mm:ss'，补 T 才解析得动
  const normalized = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(raw) ? raw.replace(' ', 'T') : raw
  const at = new Date(normalized)
  if (Number.isNaN(at.getTime())) return raw
  const day = `${pad2(at.getMonth() + 1)}-${pad2(at.getDate())}`
  return `${day} ${pad2(at.getHours())}:${pad2(at.getMinutes())}`
}

/** 有历史、但当前窗口为空时的第二句：说清楚「下一次什么时候来」。 */
function scheduleHint(input: PulseEmptyInput): string {
  if (!input.hasEnabledScreenJob) {
    return '没有已启用的定时选股任务，到【选股】手动跑一次，或去任务中心新建。'
  }
  const next = formatRunClock(input.nextScreenRunAt)
  if (!next) {
    return '已启用定时选股，但没算出下次触发时间（调度器可能没跑），可到任务中心确认。'
  }
  return `下次自动选股：${next}。也可以到【选股】立即手动跑一次。`
}

export function trackEmptyText(input: PulseEmptyInput): string {
  if (input.screenHistoryTotal === null) {
    return '选股历史没读到，先刷新；也可以到【选股】手动跑一次。'
  }
  if (input.screenHistoryTotal === 0) {
    return '还没有任何选股记录。到【选股】选一个战法立即跑一次，几十秒就有结果。'
  }
  return `近 5 个交易日没有精选入库。${scheduleHint(input)}`
}

export function todayEmptyText(input: PulseEmptyInput): string {
  if (input.screenHistoryTotal === null) {
    return '选股历史没读到，先刷新；也可以到【选股】手动跑一次。'
  }
  if (input.screenHistoryTotal === 0) {
    return '还没有任何选股记录。到【选股】选一个战法立即跑一次，几十秒就有结果。'
  }
  return `今日还没有选股记录。${scheduleHint(input)}`
}

/** 「今日选股」表头副文：今日尚未落库时的注解，同样不许写死 15:30。 */
export function todayNoteText(input: PulseEmptyInput): string {
  if (input.screenHistoryTotal === 0) return '今日尚未落库 · 到【选股】手动跑一次'
  if (!input.hasEnabledScreenJob) return '今日尚未落库 · 无定时选股任务'
  const next = formatRunClock(input.nextScreenRunAt)
  return next ? `今日尚未落库 · 下次自动选股 ${next}` : '今日尚未落库 · 定时选股未算出下次触发'
}

/**
 * 空态短句（≤14 字，直接摆在表里）。长解释仍走上面两个函数，进 tooltip。
 * 分档口径与长文本严格一致：读不到 / 一次没跑过 / 有历史但窗口空。
 */
export function trackEmptyShort(input: PulseEmptyInput): string {
  if (input.screenHistoryTotal === null) return '选股历史没读到'
  if (input.screenHistoryTotal === 0) return '还没跑过选股'
  return '近 5 日无精选入库'
}

export function todayEmptyShort(input: PulseEmptyInput): string {
  if (input.screenHistoryTotal === null) return '选股历史没读到'
  if (input.screenHistoryTotal === 0) return '还没跑过选股'
  return '今日还没有选股'
}
