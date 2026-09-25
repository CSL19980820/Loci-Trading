<script setup lang="ts">
import { Spinner } from '@/shared/components/ui/spinner'
import { computed, ref, useId, watch } from 'vue'
import { Search, RotateCcw } from '@lucide/vue'
import { Button } from '@/shared/components/ui/button'
import { Field, FieldLabel } from '@/shared/components/ui/field'
import { Input } from '@/shared/components/ui/input'
import DateField from '@/shared/components/ui/app/DateField.vue'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/components/ui/select'
import { guardianToday, guardianDaysAgo, type GuardianRange } from '../composables/useGuardianHistory'

const props = defineProps<{ value: GuardianRange; loading?: boolean; searchable?: boolean }>()
const emit = defineEmits<{ apply: [value: GuardianRange] }>()
const searchId = `history-search-${useId()}`
const dates = ref<[string, string] | null>([props.value.start, props.value.end])
const size = ref(props.value.limit)
const keyword = ref(props.value.keyword ?? '')
const presets = [{ days:1, label:'今天' }, { days:7, label:'近7天' }, { days:30, label:'近30天' }]
watch(() => `${props.value.start}/${props.value.end}`, () => { dates.value = [props.value.start, props.value.end] })
watch(() => props.value.limit, value => { size.value = value })
watch(() => props.value.keyword, value => { keyword.value = value ?? '' })
const valid = computed(() => Boolean(dates.value?.[0] && dates.value?.[1] && dates.value[0] <= dates.value[1]))
const activePreset = computed(() => {
  const today = guardianToday()
  if (dates.value?.[0] !== props.value.start || dates.value?.[1] !== props.value.end || props.value.end !== today) return 0
  return presets.find(item => guardianDaysAgo(item.days - 1, today) === props.value.start)?.days ?? 0
})
function apply(followToday = false): void {
  if (!valid.value || !dates.value || props.loading) return
  emit('apply', { start:dates.value[0], end:dates.value[1], limit:size.value, followToday, ...(props.searchable ? {keyword:keyword.value.trim()} : {}) })
}
function recent(days: number): void {
  const today = guardianToday()
  dates.value = [guardianDaysAgo(days - 1, today), today]
  apply(days === 1)
}
function reset(): void {
  const today = guardianToday()
  dates.value = [today, today]; keyword.value = ''; size.value = 20
  apply(true)
}
function onSizeChange(value: unknown): void {
  const next = Number(value)
  if (![20,50,100,200].includes(next) || next === size.value || props.loading) return
  size.value = next
  emit('apply', { ...props.value, limit:next })
}
</script>
<template>
  <form class="history-filter" aria-label="历史查询条件" @submit.prevent="apply()">
    <Field v-if="searchable" class="history-search">
      <FieldLabel :for="searchId" class="sr-only">名称或代码</FieldLabel>
      <div class="history-search-control"><Search aria-hidden="true" /><Input :id="searchId" v-model="keyword" placeholder="名称 / 代码" aria-label="名称或代码" :maxlength="80" autocomplete="off" /></div>
    </Field>
    <div class="history-presets" role="group" aria-label="快捷区间">
      <Button v-for="item in presets" :key="item.days" access="read" type="button" size="sm" :disabled="loading"
        :variant="activePreset === item.days ? 'secondary' : 'outline'" :aria-pressed="activePreset === item.days" class="history-preset" @click="recent(item.days)">{{ item.label }}</Button>
    </div>
    <div class="history-period">
      <DateField v-model="dates" type="daterange" value-format="YYYY-MM-DD" aria-label="查询日期范围" start-placeholder="开始日期" end-placeholder="结束日期" class="w-full" />
    </div>
    <Select :model-value="size" :disabled="loading" @update:model-value="onSizeChange">
      <SelectTrigger class="history-size" size="sm" aria-label="每页条数"><SelectValue /></SelectTrigger>
      <SelectContent><SelectItem v-for="n in [20,50,100,200]" :key="n" :value="n">{{ n }}条 / 页</SelectItem></SelectContent>
    </Select>
    <div class="history-actions">
      <Button access="read" type="submit" size="sm" :disabled="loading || !valid"><Spinner v-if="loading" class="animate-spin" aria-hidden="true" /><Search v-else aria-hidden="true" />查询</Button>
      <Button access="read" type="button" size="sm" variant="outline" :disabled="loading" @click="reset"><RotateCcw aria-hidden="true" />重置</Button>
    </div>
  </form>
</template>
<style scoped>
.history-filter { display:flex; align-items:center; flex-wrap:wrap; gap:8px; flex:none; width:100%; min-width:0; padding-bottom:4px; }
.history-search { width:190px; min-width:140px; flex:0 1 190px; }
.history-search-control { position:relative; width:100%; }.history-search-control>svg { position:absolute; top:50%; left:10px; transform:translateY(-50%); width:14px; height:14px; color:var(--text-tertiary); pointer-events:none; }
.history-search-control :deep(input) { height:32px; padding-left:31px; font-size:12px; }
.history-size { width:100px; flex:none; }
.history-presets { display:inline-flex; align-items:center; flex:none; }
.history-preset { padding-inline:9px; border-radius:0; }.history-preset:first-child { border-radius:6px 0 0 6px; }.history-preset:last-child { border-radius:0 6px 6px 0; }.history-preset+.history-preset { margin-left:-1px; }
.history-preset[aria-pressed=true] { background:var(--seal-soft); color:var(--seal-ink); border-color:var(--seal-border); position:relative; z-index:1; }
.history-period { width:255px; max-width:100%; min-width:0; flex:0 1 255px; }
.history-actions { display:flex; align-items:center; gap:8px; margin-left:auto; flex:none; }
@media(max-width:767px) {
 .history-search { flex:1 0 100%; width:100%; order:0; }
 .history-presets { order:1; }.history-size { order:1; margin-left:auto; }
 .history-period { order:2; flex:1 0 100%; width:100%; }
 .history-actions { order:3; }.history-search-control :deep(input) { height:36px; font-size:14px; }
}
</style>
