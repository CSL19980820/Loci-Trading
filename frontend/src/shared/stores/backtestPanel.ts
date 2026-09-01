/**
 * 回测面板的结果暂存。
 *
 * 面板在工坊里是 `v-show`、在策稿页是 `v-if`——后者切个 Tab 就把组件卸载了，
 * 几十秒跑出来的结果跟着一起没。结果本身不属于某个组件实例，提到 store 里，
 * 组件回来还能接上。
 *
 * 只在**输入完全一致**（战法 + 区间）时才回填：`resultMeta` 是按当前输入实时
 * 拼的，拿旧结果配新标题就是张冠李戴。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

import type { BacktestResult, HorizonBacktestResult } from '@/shared/types/quant'

export interface BacktestPanelSnapshot {
  /** `战法|开始|结束`；换一组输入就不再回填 */
  key: string
  horizon: HorizonBacktestResult | null
  trade: BacktestResult | null
}

export const useBacktestPanelStore = defineStore('backtestPanel', () => {
  /** scope：工坊面板与策稿页锁定战法的面板各存各的 */
  const snapshots = ref<Record<string, BacktestPanelSnapshot>>({})

  function recall(scope: string, key: string): BacktestPanelSnapshot | null {
    const hit = snapshots.value[scope]
    if (!hit || hit.key !== key) return null
    return hit
  }

  function remember(scope: string, snapshot: BacktestPanelSnapshot): void {
    snapshots.value = { ...snapshots.value, [scope]: snapshot }
  }

  return { snapshots, recall, remember }
})
