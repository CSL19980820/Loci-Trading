/**
 * BasicTable 的数据来源与分页：`dataSource` 受控与 `request` 自取两种模式，
 * 外加请求世代。
 *
 * 拆出来是因为这段是**唯一有时序风险**的部分：翻页 / 换页长 / 刷新会并发发请求，
 * 晚到的旧响应必须被丢弃，组件卸载后在途的响应也不能再写 `rows`。这些不变量
 * 只跟 `requestGeneration` 有关，和渲染、列设置、高度自适应一行都不搭；混在
 * 300 行 setup 里，改渲染的人很容易在中间插一句 `rows.value = ...` 就破了它。
 *
 * 两个 watch 的浅依赖（不 deep）与 shallowRef 是既有的性能结论，原样搬过来，
 * 别改回 deep。
 */
import { computed, onMounted, onUnmounted, reactive, ref, shallowRef, watch } from 'vue'

import type { BasicTablePagination, BasicTableRequest } from './basicTableTypes'

/** 只取 BasicTable props 里与取数有关的四项；组件的完整 props 结构上兼容。 */
export type BasicTableSourceProps = {
  dataSource?: Record<string, unknown>[]
  request?: BasicTableRequest
  pagination?: BasicTablePagination | boolean
  hasDefaultRequest?: boolean
}

export function useBasicTableSource(props: BasicTableSourceProps) {
  // shallowRef：几千行的业务表不必再被本组件深度代理一层。写入全是整表替换
  // （见下方两处 `rows.value = …`）；行内字段的响应式由父层自己的 ref 提供。
  const rows = shallowRef<Record<string, unknown>[]>([])
  const innerLoading = ref(false)
  let requestGeneration = 0

  const pager = reactive({
    currentPage: 1,
    pageSize: 20,
    total: 0,
  })

  const showPager = computed(() => props.pagination !== false)

  const pagerOpts = computed(() => {
    const base =
      typeof props.pagination === 'object' && props.pagination
        ? props.pagination
        : ({} as BasicTablePagination)
    return {
      pageSizes: base.pageSizes ?? [10, 20, 30, 40, 50, 80],
      layout: base.layout ?? 'total, sizes, prev, pager, next, jumper',
      background: base.background ?? true,
      hideOnSinglePage: base.hideOnSinglePage ?? false,
    }
  })

  // 依赖只需要「数组换了」或「长度变了」；原来的 deep 会在每次触发时遍历
  // 全部行的每个字段（几千行 × 几十列），而回调根本不读字段值。
  // 元素级改动仍由父层自己的 ref 驱动重渲染，不经这个 watch。
  watch(
    [() => props.dataSource, () => props.dataSource?.length],
    ([list]) => {
      if (props.request) return
      rows.value = list ?? []
      pager.total =
        typeof props.pagination === 'object' && props.pagination?.total != null
          ? props.pagination.total
          : (list?.length ?? 0)
    },
    { immediate: true },
  )

  // 只有三个标量字段，逐个监听即可，不必深遍历整个对象。
  watch(
    () => {
      const p = typeof props.pagination === 'object' ? props.pagination : null
      return p ? [p.currentPage, p.pageSize, p.total] : null
    },
    (values) => {
      if (!values) return
      const [currentPage, pageSize, total] = values
      if (currentPage != null) pager.currentPage = currentPage
      if (pageSize != null) pager.pageSize = pageSize
      if (total != null) pager.total = total
    },
    { immediate: true },
  )

  async function fetch(opt: Record<string, unknown> = {}, resetPage = false): Promise<void> {
    if (!props.request) return
    if (resetPage) pager.currentPage = 1
    const generation = ++requestGeneration
    innerLoading.value = true
    try {
      const result = await props.request({
        ...opt,
        currentPage: pager.currentPage,
        pageSize: pager.pageSize,
      })
      if (generation !== requestGeneration) return
      rows.value = result.list
      pager.total = result.total
    } finally {
      if (generation === requestGeneration) innerLoading.value = false
    }
  }

  function reloadTable(opt: Record<string, unknown> = {}): Promise<void> {
    return fetch(opt, false)
  }

  function restReload(opt: Record<string, unknown> = {}): Promise<void> {
    return fetch(opt, true)
  }

  // 默认首取。原实现写在组件的 onMounted 里，与 resize 注册挤在一起；
  // 拆开后两边各自登记自己的生命周期钩子，注册顺序即调用顺序，行为不变。
  onMounted(() => {
    if (props.request && props.hasDefaultRequest) void fetch()
  })

  // 卸载即作废在途请求：世代一变，晚到的 then 分支会直接 return，不再写 rows。
  onUnmounted(() => {
    requestGeneration += 1
  })

  return { rows, innerLoading, pager, showPager, pagerOpts, fetch, reloadTable, restReload }
}
