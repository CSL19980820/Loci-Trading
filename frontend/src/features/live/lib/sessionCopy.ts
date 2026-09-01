/**
 * 会话级文案的**唯一**出处。
 *
 * 病灶复盘：重构前「已收盘，展示最近收盘数据；开盘后恢复实时推流」这句话
 * 在一屏里出现了 7 次（跑马灯 ×2 + 指数区 + 四个榜单 + 信号流），因为每个
 * 子块各自持有一份「为什么空」的判断逻辑。
 *
 * 现在：判断逻辑收归本文件，**会话级长句只允许被顶栏那一枚胶囊消费**；
 * 子块空态只准用 `blockHint()` 给的 ≤8 字短语。想再加一处长句就得先改这里，
 * 改的人自然会看到这段注释。
 */
import type { ConnectionStatus } from '../composables/useLiveBoard'

export type SessionTone = 'live' | 'warn' | 'idle'

export interface SessionDeclaration {
  /** 交易时段：早盘 / 午间休市 / 已收盘 … */
  phase: string
  /** 会话级声明短句，全屏只出现一次 */
  text: string
  tone: SessionTone
}

/**
 * 键必须与后端 `market/application/session.py` 的相位常量**逐字对齐**——
 * 那边是唯一词表。曾经两边各写一半（后端根本不发 phase），于是这里全天兜底成
 * 'closed'，连续竞价里也显示「已收盘」。
 */
const PHASE_LABELS: Record<string, string> = {
  pre_open: '待开盘',
  pre_market: '盘前竞价',
  morning: '早盘交易',
  noon_break: '午间休市',
  afternoon: '午后交易',
  closing_auction: '收盘竞价',
  closed: '已收盘',
}

export function phaseLabel(phase: string | undefined): string {
  const key = (phase ?? '').trim()
  if (!key) return '非交易时段'
  return PHASE_LABELS[key] ?? key
}

export function describeSession(
  status: ConnectionStatus,
  isLive: boolean | undefined,
  phase: string | undefined,
  /**
   * 链路正常但上游数据源没喂上来。
   *
   * 这种情况 status 就是 'connected'。不单独说一句，界面会假装一切正常，
   * 让用户对着一屏冻住的数字以为那是实时价。
   */
  dataStale = false,
  /** 采集器最近一次失败原因（`hello` / `heartbeat` 带来）；空串 = 数据源正常 */
  sourceError = '',
): SessionDeclaration {
  const label = phaseLabel(phase)

  if (status === 'offline') {
    return { phase: label, text: '连接已断开·自动重连中', tone: 'warn' }
  }
  if (status === 'reconnecting') {
    return { phase: label, text: '重连中·恢复后自动续推', tone: 'warn' }
  }
  if (isLive) {
    // 链路好、数据不动：说数据源，别说连接——连接这会儿是好的。
    if (sourceError && status === 'connected') {
      return { phase: label, text: '数据源取数失败·重试中', tone: 'warn' }
    }
    if (dataStale && status === 'connected') {
      return { phase: label, text: '数据源暂无更新·链路正常', tone: 'warn' }
    }
    return {
      phase: label,
      text: status === 'connected' ? '实时推流中' : '建立连接中',
      tone: status === 'connected' ? 'live' : 'warn',
    }
  }
  // 非交易时段。**注意措辞跟着相位走**：午休说午休，别一律说「已收盘」——
  // 12:00 顶着「已收盘」正是用户截图里那块最不像实时的地方。
  if (phase === 'noon_break') {
    return { phase: label, text: '午间休市·13:00 恢复', tone: 'idle' }
  }
  if (phase === 'pre_open' || phase === 'pre_market') {
    return { phase: label, text: '待开盘·展示最近快照', tone: 'idle' }
  }
  return { phase: label, text: '已收盘·展示最近快照', tone: 'idle' }
}

/**
 * 子块空态短语（≤8 字）。刻意不接收 sessionPhase：子块**不该**解释会话状态，
 * 那是顶栏胶囊的活。这里只回答「这一块现在没有行」。
 */
export function blockHint(status: ConnectionStatus | undefined, fallback: string): string {
  if (status === 'offline' || status === 'reconnecting') return '连接中断'
  return fallback
}
