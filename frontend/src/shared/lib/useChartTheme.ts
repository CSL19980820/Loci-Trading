import { onUnmounted, shallowRef, type ShallowRef } from 'vue'

import { readChartTokens, type ChartTokens } from '@/shared/lib/chartTokens'

/**
 * 跟随主题变化的图表 token 快照。
 *
 * 主题切换只改 <html> 上的 data-appearance / data-primary / class（见 shared/lib/theme.ts），
 * CSS 变量会实时生效，但 canvas 里的颜色是上一次 setOption 的快照。把返回的 tokens
 * 放进图表的 watch 依赖，换主题时就会重绘。
 */
export function useChartTheme(): { tokens: ShallowRef<ChartTokens> } {
  const tokens = shallowRef<ChartTokens>(readChartTokens())

  if (typeof window !== 'undefined' && typeof MutationObserver !== 'undefined') {
    const observer = new MutationObserver(() => {
      tokens.value = readChartTokens()
    })
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-appearance', 'data-primary', 'class'],
    })
    onUnmounted(() => observer.disconnect())
  }

  return { tokens }
}
