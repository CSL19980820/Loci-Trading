/**
 * BasicTable 的`offsetHeight` 自适应高度。
 *
 * 拆出来不是为了行数，而是为了让那条**监听器对称性**的纪律有个自己的家：
 * 注册与移除必须无条件配对，条件判断只允许出现在 calcOffsetHeight 内部。
 * 这条规矩曾经被违反过一次（见下方注释），有专门的回归用例
 * `BasicTable.resize.test.ts` 守着——它按函数名 `calcOffsetHeight` 挑监听器，
 * 改名会让那条用例静默失效。
 */
import { onMounted, onUnmounted, ref, watch } from 'vue'

/** 只取 BasicTable props 里与高度有关的一项。 */
export type BasicTableHeightProps = {
  offsetHeight?: number
}

export function useBasicTableHeight(props: BasicTableHeightProps) {
  const autoHeight = ref<number | undefined>()

  function calcOffsetHeight(): void {
    if (!props.offsetHeight) {
      autoHeight.value = undefined
      return
    }
    autoHeight.value = Math.max(120, window.innerHeight - props.offsetHeight)
  }

  // 注册/移除都必须无条件：以前两边都包在 `if (props.offsetHeight)` 里，
  // prop 在生命周期中间变化（0 → 非 0 或反过来）就会漏掉一次 remove，监听器永久泄漏。
  // calcOffsetHeight 自己在 offsetHeight 为空时会置空高度，所以空跑无副作用。
  onMounted(() => {
    calcOffsetHeight()
    window.addEventListener('resize', calcOffsetHeight)
  })

  onUnmounted(() => {
    window.removeEventListener('resize', calcOffsetHeight)
  })

  watch(() => props.offsetHeight, calcOffsetHeight)

  return { autoHeight }
}
