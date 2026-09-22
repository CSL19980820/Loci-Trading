/**
 * 壳层提醒（toast 版）。
 *
 * 以前这些跨页状态挤在一条 34px 定高的状态轨里，把每个页面的内容整体往下压一行。
 * 现在统一走 sonner：有状态才出现、不占版面；**持续态用固定 id 原地更新**，
 * 状态消失就 dismiss，所以同一种状态反复变化只会有一条气泡，不会堆叠。
 *
 * 四类：
 *   1 初始密码（阻塞）—— 常驻，带「去修改」
 *   2 本页加载失败 —— 常驻，带「重试 / 忽略」
 *   3 补行情进度 —— loading 气泡，百分比原地刷新
 *   4 选股进行中 / 已放弃的残影 —— loading / info 气泡，带「查看进度」「停止」
 *
 * 选股工作台自带整块进度面板，在那一页不再重复弹气泡。
 */
import { computed, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'

import { useMarketSyncGate } from '@/shared/composables/useMarketSyncGate'
import { confirmAction } from '@/shared/lib/confirm'
import { strategyLabel } from '@/shared/lib/format'
import { usePalaceStore } from '@/shared/stores/palace'
import { useScreenRunStore } from '@/shared/stores/screenRun'
import { useUserStore } from '@/shared/stores/user'

/** 固定 id：同一个状态反复触发只更新那一条 */
const NOTICE_ID = {
  password: 'shell-notice-password',
  loadError: 'shell-notice-load-error',
  sync: 'shell-notice-sync',
  screenRun: 'shell-notice-screen-run',
  abandoned: 'shell-notice-abandoned',
} as const

/** 常驻气泡：不点不消失 */
const STICKY = Number.POSITIVE_INFINITY

export function useShellNotices(options: { reload: () => void }): void {
  const router = useRouter()
  const route = useRoute()
  const userStore = useUserStore()
  const palace = usePalaceStore()
  const screenRun = useScreenRunStore()
  const { syncing, syncPercent, syncMessage } = useMarketSyncGate()
  const { running, runningStrategies, abandoned } = storeToRefs(screenRun)

  const onWorkbench = computed(() => route.name === 'screen-history')
  const primarySlug = computed(() => runningStrategies.value[0] ?? '')
  const primaryPercent = computed(() => screenRun.percentFor(primarySlug.value))
  const extraCount = computed(() => Math.max(0, runningStrategies.value.length - 1))
  const runDescription = computed(() => {
    const rows = runningStrategies.value
      .map((slug) => screenRun.detailFor(slug))
      .filter(Boolean)
    return rows.length ? rows.join(' ｜ ') : '正在跑选股'
  })

  function goAccount(): void {
    void router.push('/account')
  }

  function goProgress(): void {
    void router.push({
      name: 'screen-history',
      query: primarySlug.value ? { select: `engine:${primarySlug.value}` } : undefined,
    })
  }

  /**
   * 「停止」是协作式的，不是立刻掐断。
   *
   * 后端 `POST /api/screen/run/cancel?strategy=` 只立一面旗，选股线程在**下一个交易
   * 日**的检查点才退出——当前这一日会先跑完并照常入库。所以确认框要把两件事都说清：
   * 会停，但不是马上；已经跑完的不会回滚。
   * 并行多战法时不给「停止」：指谁全靠猜，工作台里每条进度旁边都有自己的入口。
   */
  async function stopRun(): Promise<void> {
    const slug = primarySlug.value
    if (!slug) return
    const label = strategyLabel(slug) || slug
    const ok = await confirmAction({
      title: `停止「${label}」这次选股？`,
      message: '正在跑的这一个交易日会先跑完并照常入库，之后不再继续。已经入库的候选不会撤销。',
      confirmText: '停止',
      cancelText: '继续跑',
    })
    if (!ok) return
    await screenRun.abandon(slug)
    const stopped = screenRun.abandonedFor(slug)?.stopping
    toast[stopped ? 'info' : 'warning'](
      stopped ? '已请求停止 · 当前交易日跑完后结束' : '没能通知到后端 · 这一轮仍会在后台跑完',
    )
  }

  // 1 初始密码
  watch(
    () => userStore.mustChangePassword,
    (must) => {
      if (!must) {
        toast.dismiss(NOTICE_ID.password)
        return
      }
      toast.warning('账号仍在用初始密码', {
        id: NOTICE_ID.password,
        description: '请尽快改掉再继续使用',
        duration: STICKY,
        action: { label: '去修改', onClick: goAccount },
      })
    },
    { immediate: true },
  )

  // 2 本页加载失败
  watch(
    () => palace.error,
    (err) => {
      if (!err) {
        toast.dismiss(NOTICE_ID.loadError)
        return
      }
      toast.error('本页数据加载失败', {
        id: NOTICE_ID.loadError,
        description: err,
        duration: STICKY,
        action: { label: '重试', onClick: () => options.reload() },
        cancel: { label: '忽略', onClick: () => palace.clearError() },
      })
    },
    { immediate: true },
  )

  // 3 补行情进度：百分比原地刷新（进度只在标题里出现一次）
  watch(
    [syncing, syncPercent, syncMessage],
    ([busy, percent, message]) => {
      if (!busy) {
        toast.dismiss(NOTICE_ID.sync)
        return
      }
      toast.loading(`同步中 ${Math.round(Number(percent) || 0)}%`, {
        id: NOTICE_ID.sync,
        description: message || '正在补行情',
        duration: STICKY,
      })
    },
    { immediate: true },
  )

  // 4 选股进行中 / 已放弃的残影
  watch(
    [running, runningStrategies, primaryPercent, abandoned, onWorkbench],
    () => {
      if (running.value && !onWorkbench.value) {
        const name = strategyLabel(primarySlug.value)
        toast.loading(
          `选股${name ? ` ${name}` : ''} ${primaryPercent.value}%${extraCount.value ? ` +${extraCount.value}` : ''}`,
          {
            id: NOTICE_ID.screenRun,
            description: runDescription.value,
            duration: STICKY,
            action: { label: '查看进度', onClick: goProgress },
            cancel:
              runningStrategies.value.length === 1
                ? { label: '停止', onClick: () => void stopRun() }
                : undefined,
          },
        )
      } else {
        toast.dismiss(NOTICE_ID.screenRun)
      }

      if (!running.value && abandoned.value && !onWorkbench.value) {
        const name = strategyLabel(abandoned.value.strategy)
        toast.info(`选股已放弃${name ? ` · ${name}` : ''}`, {
          id: NOTICE_ID.abandoned,
          description: `停在 ${abandoned.value.percent}%`,
          duration: STICKY,
          action: {
            label: '知道了',
            onClick: () => {
              const slug = abandoned.value?.strategy
              if (slug) screenRun.dismissAbandoned(slug)
              toast.dismiss(NOTICE_ID.abandoned)
            },
          },
        })
      } else {
        toast.dismiss(NOTICE_ID.abandoned)
      }
    },
    { immediate: true, deep: true },
  )
}
