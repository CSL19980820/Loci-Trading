/**
 * BasicTable 的高度。两路互不抢：
 *   offsetHeight —— 视口减去偏移，给「按窗口扣顶栏」的旧页
 *   fillHeight   —— 表体 clientHeight 的像素值，给 height="100%" 的页级表
 *
 * 监听器对称性：注册与移除必须无条件配对，条件判断只允许出现在
 * calcOffsetHeight / measureFill 内部。回归用例 `BasicTable.resize.test.ts`
 * 按函数名 `calcOffsetHeight` 挑监听器，改名会让那条用例静默失效。
 */
import { onMounted, onUnmounted, ref, watch, type Ref } from 'vue'

/** 只取 BasicTable props 里与高度有关的一项。 */
export type BasicTableHeightProps = {
  offsetHeight?: number
}

export function useBasicTableHeight(
  props: BasicTableHeightProps,
  options: {
    bodyRef?: Ref<HTMLElement | undefined>
    fillParent?: () => boolean
  } = {},
) {
  const autoHeight = ref<number | undefined>()
  const fillHeight = ref<number | undefined>()

  function calcOffsetHeight(): void {
    if (!props.offsetHeight) {
      autoHeight.value = undefined
      return
    }
    autoHeight.value = Math.max(120, window.innerHeight - props.offsetHeight)
  }

  function measureFill(): void {
    const el = options.bodyRef?.value
    if (!el || !options.fillParent?.()) {
      fillHeight.value = undefined
      return
    }
    const next = Math.round(el.clientHeight)
    if (next > 0) {
      fillHeight.value = next
      return
    }
    requestAnimationFrame(() => {
      const retry = Math.round(el.clientHeight)
      fillHeight.value = retry > 0 ? retry : undefined
    })
  }

  let observer: ResizeObserver | undefined

  function watchBody(el: HTMLElement | undefined): void {
    observer?.disconnect()
    if (!el || !options.fillParent?.() || !observer) {
      measureFill()
      return
    }
    observer.observe(el)
    measureFill()
  }

  onMounted(() => {
    calcOffsetHeight()
    window.addEventListener('resize', calcOffsetHeight)
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(() => measureFill())
    }
    watchBody(options.bodyRef?.value)
  })

  onUnmounted(() => {
    window.removeEventListener('resize', calcOffsetHeight)
    observer?.disconnect()
  })

  watch(() => props.offsetHeight, calcOffsetHeight)
  watch(() => options.bodyRef?.value, (el) => watchBody(el), { flush: 'post' })
  watch(() => options.fillParent?.(), () => watchBody(options.bodyRef?.value), { flush: 'post' })

  return { autoHeight, fillHeight }
}
