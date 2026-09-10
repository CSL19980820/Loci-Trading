/**
 * 候选池的筛选草稿：三个筛选字段、shared BasicForm 的 schema、以及递给查询的参数。
 *
 * 拆出来的界线是「草稿 vs 结果」：这里只管用户还在改的那份表单值与它到查询参数的
 * 换算（空串要变成 undefined，日期区间要摊成 start/end），PoolView 那边管的是拿到
 * 结果之后的事——选中、读数、删除。schema 里的战法选项要读目录，所以目录 ref 传进来。
 */
import { computed, reactive, type Ref } from 'vue'

import type { BasicFormSchema } from '@/shared/components/ui/BasicForm.vue'
import { formValuesEqual } from '@/shared/components/ui/basicFormEqual'
import type { StrategyInfo } from '@/shared/types/quant'

export function usePoolFilters(strategies: Ref<StrategyInfo[]>) {
  const filters = reactive({
    strategy: '',
    decision: '',
    dateRange: null as [string, string] | null,
  })

  const filterModel = computed({
    get: () => filters as Record<string, unknown>,
    set: (value: Record<string, unknown>) => {
      filters.strategy = String(value.strategy ?? '')
      filters.decision = String(value.decision ?? '')
      const range = value.dateRange
      const nextRange =
        Array.isArray(range) && range.length === 2
          ? ([String(range[0] ?? ''), String(range[1] ?? '')] as [string, string])
          : null
      if (!formValuesEqual(filters.dateRange, nextRange)) filters.dateRange = nextRange
    },
  })

  const filterSchemas = computed<BasicFormSchema[]>(() => [
    {
      field: 'strategy',
      label: '战法',
      component: 'select',
      componentProps: {
        clearable: true,
        filterable: true,
        placeholder: '全部',
        options: strategies.value.map((item) => ({ label: item.name, value: item.slug })),
      },
    },
    {
      field: 'decision',
      label: '裁决',
      component: 'select',
      componentProps: {
        clearable: true,
        placeholder: '全部',
        options: [
          { label: '精选', value: '精选' },
          { label: '落选', value: '落选' },
          { label: '观察', value: '观察' },
        ],
      },
    },
    {
      field: 'dateRange',
      label: '日期',
      component: 'date-picker',
      componentProps: {
        type: 'daterange',
        'value-format': 'YYYY-MM-DD',
        'start-placeholder': '开始',
        'end-placeholder': '结束',
        clearable: true,
      },
    },
  ])

  const queryFilters = computed(() => {
    const [start, end] = filters.dateRange ?? []
    return {
      strategy: filters.strategy || undefined,
      decision: filters.decision || undefined,
      start: start || undefined,
      end: end || undefined,
      limit: 1000,
    }
  })

  return { filters, filterModel, filterSchemas, queryFilters }
}
