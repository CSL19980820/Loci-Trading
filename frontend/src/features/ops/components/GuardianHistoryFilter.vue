<script setup lang="ts">
import { ref, watch } from 'vue'
import { guardianToday, guardianDaysAgo, type GuardianRange } from '../composables/useGuardianHistory'
const props = defineProps<{ value: GuardianRange; loading?: boolean }>()
const emit = defineEmits<{ apply: [value: GuardianRange] }>()
const dates = ref<[string, string]>([props.value.start, props.value.end])
const size = ref(props.value.limit)
watch(() => props.value, value => { dates.value = [value.start, value.end]; size.value = value.limit })
function apply() {
  if (!dates.value?.[0] || !dates.value?.[1]) return
  emit('apply', { start: dates.value[0], end: dates.value[1], limit: size.value, followToday: false })
}
function recent(days: number) {
  const today = guardianToday()
  emit('apply', { start: guardianDaysAgo(days - 1, today), end: today, limit: size.value, followToday: days === 1 })
}
</script>
<template>
  <div class="history-filter" aria-label="历史查询条件">
    <el-button-group><el-button @click="recent(1)">今天</el-button><el-button @click="recent(7)">近7天</el-button><el-button @click="recent(30)">近30天</el-button></el-button-group>
    <el-date-picker v-model="dates" type="daterange" value-format="YYYY-MM-DD" format="YYYY-MM-DD" :clearable="false" start-placeholder="开始日期" end-placeholder="结束日期" aria-label="查询日期范围" />
    <el-select v-model="size" class="history-size" aria-label="每页条数"><el-option v-for="n in [20, 50, 100, 200]" :key="n" :value="n" :label="`${n}条 / 页`" /></el-select>
    <el-button type="primary" :loading="loading" @click="apply">查询</el-button>
    <span class="history-hint">北京时间 · 仅查询所选范围</span>
  </div>
</template>
<style scoped>
.history-filter { display: flex; flex-wrap: wrap; align-items: center; gap: var(--gap-2); padding-block: var(--gap-2); flex-shrink: 0; min-width: 0; }
.history-size { width: 108px; }
.history-filter :deep(.el-date-editor) { flex: 0 1 270px; max-width: 100%; min-width: 0; }
.history-hint { font-size: var(--fs-aux); color: var(--muted); }
</style>
