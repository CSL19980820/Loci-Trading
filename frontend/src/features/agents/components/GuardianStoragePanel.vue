<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import { toast } from 'vue-sonner'
import { Archive, Settings } from '@lucide/vue'
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import { Button } from '@/shared/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/shared/components/ui/dialog'
import { Label } from '@/shared/components/ui/label'
import {
  NumberField,
  NumberFieldContent,
  NumberFieldDecrement,
  NumberFieldIncrement,
  NumberFieldInput,
} from '@/shared/components/ui/number-field'
import { confirmAction } from '@/shared/lib/confirm'
import { getGuardianStorage, saveGuardianStorage, cleanGuardianStorage } from '@/shared/api/stock_agents'
import type { GuardianStorageStats } from '@/shared/types/stock_agents'

withDefaults(defineProps<{ showActions?: boolean }>(), { showActions: true })
const stats = shallowRef<GuardianStorageStats | null>(null)
const summary = computed(() => stats.value ? `${stats.value.full_entries} 条完整日记 · ${stats.value.compacted_entries} 条已归档` : '')
const open = ref(false)
const busy = ref(false)
defineExpose({ summary, configure, cleanup, busy })
const error = ref('')
const draft = ref({ days:30,max_entries:2000,cleanup_hours:24 })
let controller:AbortController | undefined
let timer:ReturnType<typeof setTimeout> | undefined
let disposed = false
async function load() {
  controller?.abort(); controller = new AbortController()
  try { const result = await getGuardianStorage(controller.signal); if (!disposed) stats.value = result }
  catch(e) { if (!controller.signal.aborted && !disposed) error.value = e instanceof Error ? e.message : String(e) }
}
async function poll() { if (disposed) return; if (!document.hidden && !open.value && !busy.value) await load(); if (!disposed) timer = setTimeout(poll,30000) }
function configure() { draft.value = { ...(stats.value?.retention || draft.value) }; error.value = ''; open.value = true }
async function save() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { stats.value = await saveGuardianStorage(draft.value); open.value = false; toast.success('日记保留策略已保存') }
  catch(e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
async function cleanup() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try {
    const preview = await cleanGuardianStorage(true)
    if (!preview.eligible) { toast.info('没有符合保留策略的过期详细日记'); return }
    const proceed = await confirmAction({ message: `本批压缩 ${preview.eligible} 条过期日记的详细上下文，保留摘要、运行槽、财务账本和最近40次完整记录。`, title: '清理详细日记', confirmText: '清理', cancelText: '取消', danger: true })
    if (!proceed) return
    const result = await cleanGuardianStorage(false)
    toast.success(`已清理 ${result.removed} 条详细日记${result.more_possible ? '，其余将继续分批处理' : ''}`)
    await load()
  } catch(e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
onMounted(() => { void load(); timer = setTimeout(poll,30000) })
onUnmounted(() => { disposed = true; controller?.abort(); clearTimeout(timer) })
</script>
<template>
  <div v-if="showActions" class="storage-actions">
    <Button variant="outline" size="sm" :disabled="busy" @click="configure"><Settings aria-hidden="true" />保留策略</Button>
    <Button variant="outline" size="sm" :disabled="busy" @click="cleanup"><Archive aria-hidden="true" />清理过期详情</Button>
  </div>
  <p v-if="error && !open" role="alert" class="storage-error">{{ error }}</p>
  <Dialog v-model:open="open">
    <DialogContent class="sm:max-w-lg" :dismissable="!busy" :show-close-button="!busy">
      <DialogHeader class="text-left"><DialogTitle>天才交易员 · 日记保留策略</DialogTitle></DialogHeader>
      <Alert v-if="error" variant="destructive"><AlertTitle class="line-clamp-none">{{ error }}</AlertTitle></Alert>
      <form class="retention-form" @submit.prevent="save">
        <div class="retention-field"><Label for="guardian-retention-days">完整日记保留天数（0为关闭天数限制）</Label><NumberField v-model="draft.days" :min="0" :max="3650"><NumberFieldContent><NumberFieldInput id="guardian-retention-days" class="text-left" /><NumberFieldIncrement /><NumberFieldDecrement /></NumberFieldContent></NumberField></div>
        <div class="retention-field"><Label for="guardian-retention-entries">完整日记最多条数（0为关闭条数限制）</Label><NumberField v-model="draft.max_entries" :min="0" :max="100000" :step="100"><NumberFieldContent><NumberFieldInput id="guardian-retention-entries" class="text-left" /><NumberFieldIncrement /><NumberFieldDecrement /></NumberFieldContent></NumberField></div>
        <div class="retention-field"><Label for="guardian-retention-hours">清理检查间隔（小时）</Label><NumberField v-model="draft.cleanup_hours" :min="1" :max="168"><NumberFieldContent><NumberFieldInput id="guardian-retention-hours" class="text-left" /><NumberFieldIncrement /><NumberFieldDecrement /></NumberFieldContent></NumberField></div>
      </form>
      <p class="storage-note">超过天数或条数的旧详细上下文会分批压缩。当天、运行中及最近40次完整日记始终保留；成交账本、账户、报告与防重复运行凭据不清理。此设置不改变交易算法或提示词。</p>
      <DialogFooter><Button access="read" variant="outline" :disabled="busy" @click="open = false">取消</Button><Button :disabled="busy" @click="save">保存策略</Button></DialogFooter>
    </DialogContent>
  </Dialog>
</template>
<style scoped>
.guardian-storage { flex: none; min-width: 0; border-top: 1px solid var(--border-subtle); }
.guardian-storage > summary { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 12px; padding: 10px 0; cursor: pointer; list-style: none; color: var(--text-secondary); font-size: 12px; }
.guardian-storage > summary::-webkit-details-marker { display: none; }
.guardian-storage > summary > svg { width: 14px; height: 14px; flex: none; transition: transform .15s; }
.guardian-storage[open] > summary > svg { transform: rotate(180deg); }
.guardian-storage > summary:hover { color: var(--text-primary); }
.guardian-storage > summary:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: -2px; }
.storage-summary { color: var(--text-tertiary); font-size: 11px; font-variant-numeric: tabular-nums; }
.storage-body { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; padding: 0 0 12px; }
.storage-actions { display: flex; flex-wrap: wrap; gap: var(--gap-2); }
.storage-note { margin: 0; color: var(--text-tertiary); font-size: var(--fs-aux); line-height: 1.7; }
.storage-error { margin: var(--gap-2) 0 0; color: var(--stamp); font-size: var(--fs-aux); }
.retention-form { margin-top: var(--gap-3); display: grid; gap: var(--gap-3); }
.retention-field { display: grid; gap: var(--gap-1); }
.retention-field :deep(label) { color: var(--text-tertiary); font-size: var(--fs-aux); }
@media (max-width: 640px) {
  .storage-actions { grid-column: 1 / -1; grid-row: auto; justify-self: stretch; margin-top: var(--gap-2); }
}
</style>
