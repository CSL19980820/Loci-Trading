<script setup lang="ts" generic="T = string | string[] | null">
import { computed, nextTick, ref, shallowRef, useAttrs, watch, type StyleValue } from 'vue'
import type { DateValue } from '@internationalized/date'
import type { DateRange } from 'reka-ui'
import { useMediaQuery } from '@vueuse/core'
import { CalendarDays, X } from '@lucide/vue'
import { Calendar } from '../calendar'
import RangeCalendar from '../range-calendar/RangeCalendar.vue'
import { Button } from '../button'
import { Input } from '../input'
import { Popover, PopoverTrigger, PopoverContent } from '../popover'
import { useFieldControl } from './context'
import { nativeDate, readDate, readTime, validTime, writeDate } from './date-value'

defineOptions({ inheritAttrs: false })
const props = withDefaults(defineProps<{
  modelValue?: T; type?: string; valueFormat?: string; placeholder?: string;
  startPlaceholder?: string; endPlaceholder?: string; rangeSeparator?: string; disabled?: boolean;
  clearable?: boolean; disabledDate?: (date: Date) => boolean
}>(), { type: 'date', clearable: true, startPlaceholder: '开始日期', endPlaceholder: '结束日期', rangeSeparator: '—' })
const emit = defineEmits<{ 'update:modelValue': [value: T]; change: [value: T]; clear: [] }>()
const attrs = useAttrs()
const field = useFieldControl()
const root = ref<HTMLElement>()
const open = ref(false)
const draft = shallowRef<DateRange>({ start: undefined, end: undefined })
const times = ref(['00:00', '23:59'])
const range = computed(() => props.type.includes('range'))
const datetime = computed(() => props.type.includes('datetime'))
const narrow = useMediaQuery('(max-width: 640px)')
const disabled = computed(() => props.disabled || field.disabled.value)
const values = computed<unknown[]>(() => Array.isArray(props.modelValue) ? props.modelValue : [props.modelValue])
const committedStart = computed(() => readDate(values.value[0]))
function resetDraft() {
  draft.value = { start: readDate(values.value[0]), end: readDate(values.value[1]) }
  times.value = [readTime(values.value[0]), readTime(values.value[1], '23:59')]
}
watch(() => props.modelValue, resetDraft, { immediate: true, deep: true })
watch(open, value => { if (value) resetDraft() })
watch(disabled, value => { if (value) open.value = false })
const invalid = computed(() => {
  if (datetime.value && times.value.slice(0, range.value ? 2 : 1).some(time => !validTime(time))) return '请输入有效时间，例如 09:30'
  const { start, end } = draft.value
  if (start && props.disabledDate?.(nativeDate(start))) return '该日期不可选'
  if (range.value && end && props.disabledDate?.(nativeDate(end))) return '该日期不可选'
  if (range.value && start && end && (start.compare(end) > 0 || (datetime.value && start.compare(end) === 0 && times.value[0] > times.value[1]))) return '结束时间不能早于开始时间'
  return ''
})
const complete = computed(() => Boolean(draft.value.start && (!range.value || draft.value.end)))
function apply() {
  if (disabled.value || !complete.value || invalid.value) return
  const { start, end } = draft.value
  const value = (range.value
    ? [writeDate(start!, times.value[0], datetime.value, props.valueFormat), writeDate(end!, times.value[1], datetime.value, props.valueFormat)]
    : writeDate(start!, times.value[0], datetime.value, props.valueFormat)) as T
  emit('update:modelValue', value)
  emit('change', value)
  field.validate()
  open.value = false
}
function selectDate(value: DateValue | DateValue[] | undefined) {
  if (!value || Array.isArray(value)) return
  draft.value = { start: value, end: undefined }
  if (!datetime.value) apply()
}
function selectRange(value: DateRange) {
  draft.value = value
  if (value.start && value.end && !datetime.value) apply()
}
async function clear() {
  if (disabled.value) return
  open.value = false
  emit('update:modelValue', null as T)
  emit('change', null as T)
  emit('clear')
  field.validate()
  await nextTick()
  root.value?.querySelector<HTMLButtonElement>('.date-field__trigger')?.focus()
}
function display(value: unknown): string {
  const date = readDate(value)
  return date ? `${date}${datetime.value ? ` ${readTime(value)}` : ''}` : ''
}
const label = computed(() => committedStart.value
  ? range.value ? `${display(values.value[0])} ${props.rangeSeparator} ${display(values.value[1]) || props.endPlaceholder}` : display(values.value[0])
  : props.placeholder || (range.value ? `${props.startPlaceholder} ${props.rangeSeparator} ${props.endPlaceholder}` : '选择日期'))
function controlAttrs() { return { ...field.bindings.value, ...Object.fromEntries(Object.entries(attrs).filter(([key]) => key !== 'class' && key !== 'style')) } }
</script>

<template>
  <div ref="root" :class="['date-field', attrs.class]" :style="attrs.style as StyleValue">
    <Popover v-model:open="open">
      <PopoverTrigger as-child>
        <Button access="read" v-bind="controlAttrs()" type="button" variant="outline" class="date-field__trigger" :class="{ 'text-muted-foreground': !committedStart }" :disabled="disabled" :title="label">
          <CalendarDays class="size-4 shrink-0" aria-hidden="true" /><span>{{ label }}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" :collision-padding="8" class="date-field__popup">
        <div v-if="range" class="date-field__selection" aria-live="polite">
          <span>{{ draft.start?.toString() || startPlaceholder }}</span><span aria-hidden="true">{{ rangeSeparator }}</span><span>{{ draft.end?.toString() || endPlaceholder }}</span>
        </div>
        <RangeCalendar v-if="range" :model-value="draft" :number-of-months="narrow ? 1 : 2" allow-non-contiguous-ranges locale="zh-CN" initial-focus
          :is-date-unavailable="disabledDate ? date => disabledDate!(nativeDate(date)) : undefined" @update:model-value="selectRange" />
        <Calendar v-else :model-value="draft.start" :default-placeholder="draft.start" locale="zh-CN" :week-starts-on="1" layout="month-and-year" initial-focus
          :is-date-unavailable="disabledDate ? date => disabledDate!(nativeDate(date)) : undefined" @update:model-value="selectDate" />
        <div v-if="datetime" class="date-field__times">
          <Label v-for="index in (range ? 2 : 1)" :key="index">
            <span>{{ range ? index === 1 ? '开始时间' : '结束时间' : '时间' }}</span>
            <Input v-model="times[index - 1]" type="text" placeholder="HH:mm" maxlength="5" :aria-invalid="!validTime(times[index - 1])" class="h-8 w-20 text-center font-mono" />
          </Label>
        </div>
        <p v-if="invalid" class="date-field__error" role="alert">{{ invalid }}</p>
        <div v-if="datetime" class="date-field__footer"><Button access="read" type="button" variant="ghost" size="sm" @click="open = false">取消</Button><Button access="read" type="button" size="sm" :disabled="!complete || Boolean(invalid)" @click="apply">确定</Button></div>
      </PopoverContent>
    </Popover>
    <Button access="read" variant="ghost" v-if="clearable && committedStart && !disabled" type="button" class="date-field__clear field-icon-button" aria-label="清空日期" @click="clear"><X class="size-3.5" aria-hidden="true" /></Button>
  </div>
</template>

<style scoped>
.date-field__selection { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 8px 12px; border-bottom: 1px solid var(--border-subtle); color: var(--text-secondary); font-size: 12px; font-variant-numeric: tabular-nums; }
.date-field__times { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 10px; padding: 10px; border-top: 1px solid var(--border-subtle); }
.date-field__times label { display: flex; align-items: center; gap: 8px; color: var(--text-secondary); font-size: 12px; }
.date-field__error { margin: 0; padding: 0 10px 8px; color: var(--stamp); font-size: 12px; }
.date-field__footer { display: flex; justify-content: flex-end; gap: 6px; padding: 0 10px 10px; }
</style>
