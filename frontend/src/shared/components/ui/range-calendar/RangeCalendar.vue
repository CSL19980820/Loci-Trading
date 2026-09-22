<script setup lang="ts">
import type { DateValue } from '@internationalized/date'
import { getLocalTimeZone, today } from '@internationalized/date'
import { reactiveOmit, useVModel } from '@vueuse/core'
import { ChevronLeft, ChevronRight } from '@lucide/vue'
import type { HTMLAttributes, Ref } from 'vue'
import {
  RangeCalendarRoot, RangeCalendarHeader, RangeCalendarHeading, RangeCalendarPrev, RangeCalendarNext,
  RangeCalendarGrid, RangeCalendarGridHead, RangeCalendarGridBody, RangeCalendarGridRow,
  RangeCalendarHeadCell, RangeCalendarCell, RangeCalendarCellTrigger, useForwardPropsEmits,
  type RangeCalendarRootProps, type RangeCalendarRootEmits,
} from 'reka-ui'
import { cn } from '@/shared/lib/utils'
import { Button } from '../button'
import CalendarCaption from '../calendar/CalendarCaption.vue'

const props = withDefaults(defineProps<RangeCalendarRootProps & { class?: HTMLAttributes['class'] }>(), { modelValue: undefined, locale: 'zh-CN', weekStartsOn: 1, fixedWeeks: true })
const emit = defineEmits<RangeCalendarRootEmits>()
const forwarded = useForwardPropsEmits(reactiveOmit(props, 'class', 'placeholder'), emit)
const placeholder = useVModel(props, 'placeholder', emit, {
  passive: true,
  defaultValue: props.defaultPlaceholder ?? props.modelValue?.start ?? today(getLocalTimeZone()),
}) as Ref<DateValue>
</script>

<template>
  <RangeCalendarRoot v-slot="{ grid, weekDays }" v-bind="forwarded" v-model:placeholder="placeholder" data-slot="range-calendar" :class="cn('range-calendar', props.class)">
    <RangeCalendarHeader class="range-calendar__header">
      <RangeCalendarPrev as-child><Button access="read" type="button" variant="ghost" size="icon-sm" aria-label="上个月"><ChevronLeft aria-hidden="true" /></Button></RangeCalendarPrev>
      <RangeCalendarHeading class="sr-only" />
      <CalendarCaption v-model:date="placeholder" :locale="locale" :disabled="disabled || readonly" />
      <RangeCalendarNext as-child><Button access="read" type="button" variant="ghost" size="icon-sm" aria-label="下个月"><ChevronRight aria-hidden="true" /></Button></RangeCalendarNext>
    </RangeCalendarHeader>
    <div class="range-calendar__months">
      <RangeCalendarGrid v-for="month in grid" :key="month.value.toString()" class="range-calendar__grid">
        <caption v-if="grid.length > 1" class="range-calendar__caption">{{ month.value.year }} 年 {{ month.value.month }} 月</caption>
        <RangeCalendarGridHead><RangeCalendarGridRow>
          <RangeCalendarHeadCell v-for="day in weekDays" :key="day" class="range-calendar__weekday">{{ day }}</RangeCalendarHeadCell>
        </RangeCalendarGridRow></RangeCalendarGridHead>
        <RangeCalendarGridBody>
          <RangeCalendarGridRow v-for="(week, index) in month.rows" :key="index">
            <RangeCalendarCell v-for="day in week" :key="day.toString()" :date="day" class="range-calendar__cell">
              <RangeCalendarCellTrigger :day="day" :month="month.value" class="range-calendar__day" />
            </RangeCalendarCell>
          </RangeCalendarGridRow>
        </RangeCalendarGridBody>
      </RangeCalendarGrid>
    </div>
  </RangeCalendarRoot>
</template>

<style scoped>
.range-calendar { padding: 10px; width: fit-content; max-width: 100%; }
.range-calendar__header { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
.range-calendar__months { display: flex; gap: 16px; }
.range-calendar__grid { border-collapse: collapse; table-layout: fixed; width: 252px; }
.range-calendar__caption { padding-bottom: 8px; font-size: 12px; color: var(--text-secondary); }
.range-calendar__weekday { width: 36px; height: 28px; text-align: center; color: var(--text-tertiary); font-size: 11px; font-weight: 400; }
.range-calendar__cell { padding: 1px 0; text-align: center; }
.range-calendar__day { display: grid; place-items: center; width: 36px; height: 34px; padding: 0; border: 0; border-radius: 4px; background: transparent; color: var(--text-primary); font-size: 12px; font-variant-numeric: tabular-nums; cursor: pointer; }
.range-calendar__day:hover { background: var(--surface-hover); }
.range-calendar__day[data-selected], .range-calendar__day[data-highlighted] { background: var(--seal-soft); color: var(--seal-ink); border-radius: 0; }
.range-calendar__day[data-selection-start], .range-calendar__day[data-selection-end] { background: var(--seal); color: var(--on-primary); border-radius: 4px; }
.range-calendar__day[data-today]:not([data-selected]) { box-shadow: inset 0 0 0 1px var(--seal-border); }
.range-calendar__day[data-outside-view] { color: var(--text-tertiary); opacity: .45; }
.range-calendar__day[data-disabled], .range-calendar__day[data-unavailable] { opacity: .35; cursor: not-allowed; }
.range-calendar__day:focus-visible { position: relative; z-index: 1; outline: 2px solid var(--focus-ring); outline-offset: 1px; }
</style>
