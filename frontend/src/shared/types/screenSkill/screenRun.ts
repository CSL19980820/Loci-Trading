/**
 * 选股进度槽：后端按「租户 × 战法」分片，多个战法可以同时在跑。这一组类型的
 * 语义细节（顶层平铺只为兼容老客户端、`busy_reason` 两种含义）写在下面的注释里，
 * 独立成文件是为了让「进度/并发」这套状态机不被结果类型的字段淹没。
 */

import type { ScreenResult } from './screenResult'

/**
 * 单个战法的进度槽。后端按「租户 × 战法」分片（`src/strategy/application/
 * screen_run_state.py`），**一个战法一份**：潜龙、三源、杨氏可以同时在跑，
 * 各有独立的 status / percent / log / result / 取消旗。
 */
export interface ScreenRunSlot {
  /** `cancelled` = 用户点了停止且后端已在检查点退出；已跑完的交易日仍已入库 */
  status: 'idle' | 'running' | 'done' | 'error' | 'cancelled' | string
  phase: string
  percent: number
  message: string
  strategy: string
  trade_date: string
  log: string[]
  result: ScreenResult | null
  error: string
  /** 后端权威开跑时刻（epoch 秒，0 = 没开跑）。有它才能说「已跑」而不是「已跟踪」 */
  started_at?: number
  /** 最后一次写进度的时刻（epoch 秒） */
  updated_at?: number
  cancel_requested?: boolean
  /**
   * 只出现在 `POST /api/screen/run` 的「占不到槽」响应里：
   *
   * - `same_strategy`：**这个**战法自己还在跑（重复点击）。快照就是它自己的，
   *   界面应当接回去继续看进度。
   * - `tenant_limit`：并发到顶。快照是最早开跑的那一个，文案要说「先停一个或
   *   等一个跑完」，不能说「引擎忙」——别的战法照样能开。
   */
  busy_reason?: 'same_strategy' | 'tenant_limit'
  running_strategies?: string[]
  max_concurrent_runs?: number
}

/**
 * `GET /api/screen/run` 的聚合响应。
 *
 * 顶层平铺的是「当前这一个」槽（最近开跑 > 最近碰过），**只为滚动升级期的老
 * 客户端**；真相在 `runs`——每个战法一条，可以同时有多条 `running`。新代码读
 * `runs` / `running_strategies`，不要拿顶层 `status` 当「引擎在不在忙」。
 */
export interface ScreenRunStatus extends ScreenRunSlot {
  runs?: Record<string, ScreenRunSlot>
}
