/**
 * 侧栏的路由分片预取。
 *
 * 与「显示哪些菜单」是两件事：这里一行都不关心菜单长什么样，只关心「用户看起来
 * 要去某个路径了，把它的 chunk 先下下来」。放在 AppSidebar 里时，它和菜单数据、
 * 弹层开关挤在同一段 setup，读的人分不清哪些是版型状态、哪些是纯性能优化——
 * 后者删掉页面照常工作，前者删掉页面就空了。
 */
import { onMounted } from 'vue'
import { useRouter, type RouteRecordNormalized } from 'vue-router'

/*
 * —— 路由分片预取 ——
 *
 * 路由组件是 `() => import(...)`，vue-router 在**导航确认前**要把分片下完。
 * 首次点某个菜单于是先卡一下才切页。这里在悬停 / 聚焦时提前把工厂跑掉：
 * 等真点下去时分片已在内存，导航是同步的。
 *
 * 失败一律吞掉：预取是锦上添花，网络不好时不该冒出一条错误提示；真导航过去时
 * vue-router 会自己再试一次并走正常的错误处理。
 */

/** 空闲时预取的高频页：盘面 / 候选池 / 选股 / 工坊。别把整张路由表都拉下来。 */
const IDLE_PREFETCH = ['/', '/pool', '/screen-history', '/quant']

export function useRoutePrefetch() {
  const router = useRouter()

  const prefetched = new Set<string>()

  function prefetchRoute(path?: string): void {
    if (!path || prefetched.has(path)) return
    prefetched.add(path)
    // 测试里的 router 是个精简 mock，没有 resolve；这里不该炸。
    if (typeof router?.resolve !== 'function') return
    let records: readonly RouteRecordNormalized[]
    try {
      records = router.resolve(path).matched
    } catch {
      return
    }
    for (const record of records) {
      for (const loader of Object.values(record.components ?? {})) {
        if (typeof loader !== 'function') continue
        try {
          void Promise.resolve((loader as () => unknown)()).catch(() => undefined)
        } catch {
          /* 工厂同步抛错：预取失败不该影响任何交互 */
        }
      }
    }
  }

  onMounted(() => {
    const warmup = (): void => IDLE_PREFETCH.forEach((path) => prefetchRoute(path))
    // requestIdleCallback 必须挂在 window 上调（脱手调用某些内核会抛 Illegal invocation）；
    // happy-dom / 老 Safari 没有它，退回一个足够晚的 setTimeout。
    if (typeof window.requestIdleCallback === 'function') {
      window.requestIdleCallback(warmup, { timeout: 3000 })
      return
    }
    window.setTimeout(warmup, 1200)
  })

  return { prefetchRoute }
}
