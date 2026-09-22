<script setup lang="ts">
import { computed, ref } from 'vue'
import type { DateValue } from '@internationalized/date'
import { createYear, toDate } from 'reka-ui/date'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../select'

const props = withDefaults(defineProps<{
  date: DateValue
  locale?: string
  layout?: 'month-and-year' | 'month-only' | 'year-only'
  years?: DateValue[]
  disabled?: boolean
}>(), { locale: 'zh-CN', layout: 'month-and-year' })
const emit = defineEmits<{ 'update:date': [date: DateValue] }>()
const yearOpen = ref(false)
const monthOpen = ref(false)
const months = computed(() => createYear({ dateObj: props.date }))
const years = computed(() => props.years?.map(date => date.year) ?? Array.from({ length: 111 }, (_, index) => props.date.year - 100 + index))
const formatter = computed(() => new Intl.DateTimeFormat(props.locale, { month: 'short' }))
function change(part: 'month' | 'year', value: unknown) {
  const number = Number(value)
  if (Number.isInteger(number)) emit('update:date', props.date.set({ [part]: number }))
}
</script>

<template>
  <div class="calendar-caption">
    <Select v-if="layout !== 'month-only'" v-model:open="yearOpen" :model-value="String(date.year)" :disabled="disabled" @update:model-value="change('year', $event)">
      <SelectTrigger aria-label="年份" class="h-8 w-auto gap-1 border-0 px-2 shadow-none" @click="yearOpen = true"><SelectValue /></SelectTrigger>
      <SelectContent position="popper" :collision-padding="8" class="max-h-64 min-w-24">
        <SelectItem v-for="year in years" :key="year" :value="String(year)">{{ year }}</SelectItem>
      </SelectContent>
    </Select>
    <span v-else class="px-1 text-ui">{{ date.year }}</span>
    <Select v-if="layout !== 'year-only'" v-model:open="monthOpen" :model-value="String(date.month)" :disabled="disabled" @update:model-value="change('month', $event)">
      <SelectTrigger aria-label="月份" class="h-8 w-auto gap-1 border-0 px-2 shadow-none" @click="monthOpen = true"><SelectValue /></SelectTrigger>
      <SelectContent position="popper" :collision-padding="8" class="max-h-64 min-w-24">
        <SelectItem v-for="month in months" :key="month.month" :value="String(month.month)">{{ formatter.format(toDate(month)) }}</SelectItem>
      </SelectContent>
    </Select>
    <span v-else class="px-1 text-ui">{{ formatter.format(toDate(date)) }}</span>
  </div>
</template>

<style scoped>
.calendar-caption { position: relative; display: flex; align-items: center; justify-content: center; min-width: 0; gap: 2px; }
</style>
