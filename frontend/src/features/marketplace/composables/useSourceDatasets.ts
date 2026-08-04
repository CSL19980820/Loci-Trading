/** 某个数据源下挂的接口清单。目录由本机安装的 akshare 反射得到，不是静态清单。 */
import { onScopeDispose, ref } from 'vue'

import { getAkshareCatalog } from '@/shared/api/quant'
import { toErrorMessage } from '@/shared/lib/errors'
import type { AkshareCatalogCapability } from '@/shared/types/quant'

export function useSourceDatasets() {
  const datasets = ref<AkshareCatalogCapability[]>([])
  const loading = ref(false)
  const error = ref('')
  let token = 0

  async function load(sourceId: string): Promise<void> {
    const current = ++token
    loading.value = true
    error.value = ''
    try {
      const catalog = await getAkshareCatalog({ source: sourceId })
      if (current !== token) return
      datasets.value = catalog.capabilities || []
    } catch (caught: unknown) {
      if (current !== token) return
      error.value = toErrorMessage(caught, '读取数据列表失败')
      datasets.value = []
    } finally {
      if (current === token) loading.value = false
    }
  }

  function reset(): void {
    token += 1
    datasets.value = []
    error.value = ''
    loading.value = false
  }

  onScopeDispose(() => {
    token += 1
  })

  return { datasets, loading, error, load, reset }
}
