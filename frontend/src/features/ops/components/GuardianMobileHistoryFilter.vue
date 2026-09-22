<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { CalendarDays, SlidersHorizontal } from '@lucide/vue'
import { Input } from '@/shared/components/ui/input'
import { Field, FieldLabel, FieldError } from '@/shared/components/ui/field'
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/shared/components/ui/select'
import { Button } from '@/shared/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogDescription } from '@/shared/components/ui/dialog'
import { guardianToday, guardianDaysAgo, type GuardianRange } from '../composables/useGuardianHistory'

const props = defineProps<{ value: GuardianRange; loading?: boolean }>()
const emit = defineEmits<{ apply: [value: GuardianRange] }>()
const open = ref(false)
const draft = ref({ ...props.value })
watch(open, value => { if (value) draft.value = { ...props.value } })
const label = computed(() => props.value.start === props.value.end ? props.value.start : `${props.value.start.slice(5)} — ${props.value.end.slice(5)}`)
const valid = computed(() => Boolean(draft.value.start && draft.value.end && draft.value.start <= draft.value.end))
function recent(days: number): void {
 const today = guardianToday()
 draft.value = { ...draft.value, start: guardianDaysAgo(days - 1, today), end: today, followToday: days === 1 }
}
function apply(): void {
 if (!valid.value || props.loading) return
 emit('apply', { ...draft.value, limit: Number(draft.value.limit) })
 open.value = false
}
</script>
<template>
 <div class="mobile-history-filter">
  <Button access="read" variant="outline" size="sm" class="mobile-history-trigger" :disabled="loading" aria-label="日期与分页筛选" @click="open = true"><CalendarDays aria-hidden="true" /><span>{{ label }}</span><SlidersHorizontal class="mobile-history-icon" aria-hidden="true" /></Button>
  <Dialog v-model:open="open">
   <DialogContent class="mobile-history-dialog sm:max-w-md">
    <DialogHeader><DialogTitle>筛选</DialogTitle><DialogDescription>选择查询日期及每页记录数。</DialogDescription></DialogHeader>
    <form id="guardian-mobile-history" class="mobile-history-form" @submit.prevent="apply">
     <div class="mobile-history-presets"><Button v-for="n in [1,7,30]" :key="n" access="read" type="button" variant="outline" @click="recent(n)">{{ n === 1 ? '今天' : `近${n}天` }}</Button></div>
     <Field><FieldLabel for="guardian-history-start">开始日期</FieldLabel><Input id="guardian-history-start" v-model="draft.start" type="date" aria-label="开始日期" required @input="draft.followToday = false" /></Field>
     <Field><FieldLabel for="guardian-history-end">结束日期</FieldLabel><Input id="guardian-history-end" v-model="draft.end" type="date" aria-label="结束日期" :min="draft.start" required @input="draft.followToday = false" /></Field>
     <Field><FieldLabel for="guardian-history-limit">每页条数</FieldLabel><Select :model-value="String(draft.limit)" @update:model-value="value => draft.limit = Number(value)"><SelectTrigger id="guardian-history-limit" aria-label="每页条数"><SelectValue /></SelectTrigger><SelectContent><SelectItem v-for="n in [20,50,100,200]" :key="n" :value="String(n)">{{ n }} 条</SelectItem></SelectContent></Select></Field>
     <FieldError v-if="!valid">开始日期不得晚于结束日期。</FieldError>
    </form>
    <DialogFooter><Button access="read" variant="outline" @click="open = false">取消</Button><Button access="read" type="submit" form="guardian-mobile-history" :disabled="!valid || loading">查询</Button></DialogFooter>
   </DialogContent>
  </Dialog>
 </div>
</template>
<style scoped>
.mobile-history-filter { min-width:0; }
.mobile-history-trigger { width:100%; min-height:36px; justify-content:flex-start; gap:7px; white-space:nowrap; }
.mobile-history-trigger span { overflow:hidden; text-overflow:ellipsis; }
.mobile-history-icon { margin-left:auto; }
.mobile-history-form { display:flex; flex-direction:column; gap:14px; }
.mobile-history-presets { display:flex; gap:8px; }
.mobile-history-presets button { flex:1; min-height:40px; }
.mobile-history-form :deep([data-slot="field"]) { display:grid; grid-template-columns:80px minmax(0,1fr); align-items:center; gap:12px; color:var(--text-secondary); font-size:13px; }
.mobile-history-form :deep(input),.mobile-history-form :deep([data-slot="select-trigger"]) { width:100%; min-width:0; height:42px; border:1px solid var(--border-default); border-radius:8px; padding:8px 10px; background:var(--surface); color:var(--text-primary); font:16px var(--font); color-scheme:inherit; }
</style>
