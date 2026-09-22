/**
 * 工作台的「停止 / 放弃跟踪」。
 *
 * 两条链路的能力**不一样**，文案因此也不能共用：
 *
 * - **选股**：后端有 `POST /api/screen/run/cancel?strategy=`，真的会停——但取消是
 *   协作式的，当前这一个交易日会先跑完并入库，之后才退出。而且**按战法点名**：
 * 停潜龙不影响并行跑着的三源、杨氏。
 * - **技能运行**：后端仍然没有中止接口（`/api/skill-runs/{id}` 只有查询/事件/回复），
 * 所以这里只能停事件流，那条线程会跑到自己结束。
 *
 * 把「停得掉」和「停不掉」写成同一句话，就是在骗人。
 */
import type { Ref } from 'vue'
import { toast } from 'vue-sonner'

import { confirmAction } from '@/shared/lib/confirm'
import { strategyLabel } from '@/shared/lib/format'
import type { useScreenRunStore } from '@/shared/stores/screenRun'

const ENGINE_DETAIL =
'正在跑的这一个交易日会先跑完并照常入库，之后不再继续。已经入库的候选不会撤销。其它战法不受影响。'

const SKILL_DETAIL =
'后端没有中止接口：这次技能运行会在后台继续跑完。放弃只是前端停掉事件流与进度。'

export function useWorkbenchAbandon(opts: {
  screenRun: ReturnType<typeof useScreenRunStore>
  /** 当前选中的战法 slug（技能时给空串） */
  engineSlug: () => string
  /** 当前选中的战法自己在不在跑 */
  engineRunning: Ref<boolean>
  skillActive: Ref<boolean>
  abandonSkill: () => void
  selectedKind: () => 'engine' | 'skill' | null
}) {
  async function confirm(detail: string, title = '放弃跟踪？', ok = '放弃跟踪'): Promise<boolean> {
    return confirmAction({
      message: detail,
      title,
      confirmText: ok,
      cancelText: '继续跑',
    })
  }

  /**
   * 停止某个战法的选股。
   *
   * `slug` 省略 = 当前选中的战法；跑道横幅上的「停止」会把并行战法的 slug 传进来。
   * 确认框里带战法名——多战法并跑时「停止这次选股？」根本说不清停的是哪一个。
   */
  async function abandonEngineRun(slug?: string): Promise<void> {
    const target = String(slug || opts.engineSlug() || '')
    if (!target || !opts.screenRun.isRunning(target)) return
    const label = strategyLabel(target) || target
    if (!(await confirm(ENGINE_DETAIL, `停止「${label}」这次选股？`, '停止'))) return
    await opts.screenRun.abandon(target)
    toast.info(
      opts.screenRun.abandonedFor(target)?.stopping
        ? `已请求停止 · ${label} 当前交易日跑完后结束`
        : `没能通知到后端 · ${label} 这一轮仍会在后台跑完`,
    )
  }

  async function abandonSkillRun(): Promise<void> {
    if (!opts.skillActive.value) return
    if (!(await confirm(SKILL_DETAIL))) return
    opts.abandonSkill()
    toast.info('已停止跟踪 · 该次技能仍在后台继续')
  }

  /** 跑道上那一个按钮：按当前选中的是战法还是技能分派。 */
  async function abandonActiveRun(): Promise<void> {
    if (opts.selectedKind() === 'skill') {
      await abandonSkillRun()
      return
    }
    await abandonEngineRun()
  }

  return { abandonEngineRun, abandonSkillRun, abandonActiveRun }
}
