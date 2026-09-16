<script setup lang="ts">
import { onMounted, onUnmounted, ref, shallowRef } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getGuardianStorage, saveGuardianStorage, cleanGuardianStorage } from '@/shared/api/stock_agents'
import type { GuardianStorageStats } from '@/shared/types/stock_agents'
const stats = shallowRef<GuardianStorageStats | null>(null)
const open = ref(false)
const busy = ref(false)
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
  try { stats.value = await saveGuardianStorage(draft.value); open.value = false; ElMessage.success('日记保留策略已保存') }
  catch(e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
async function cleanup() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try {
    const preview = await cleanGuardianStorage(true)
    if (!preview.eligible) { ElMessage.info('没有符合保留策略的过期详细日记'); return }
    try { await ElMessageBox.confirm(`本批压缩 ${preview.eligible} 条过期日记的详细上下文，保留摘要、运行槽、财务账本和最近40次完整记录。`, '清理详细日记', { type:'warning',confirmButtonText:'清理',cancelButtonText:'取消' }) }
    catch { return }
    const result = await cleanGuardianStorage(false)
    ElMessage.success(`已清理 ${result.removed} 条详细日记${result.more_possible ? '，其余将继续分批处理' : ''}`)
    await load()
  } catch(e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
onMounted(() => { void load(); timer = setTimeout(poll,30000) })
onUnmounted(() => { disposed = true; controller?.abort(); clearTimeout(timer) })
</script>
<template>
  <section class="guardian-storage"><div><h3>历史与存储</h3><p v-if="stats">累计 {{ stats.total_runs }} 次工作 · {{ stats.total_trades }} 笔成交 · {{ stats.total_reports }} 份报告</p><p v-if="stats" class="storage-note">完整日记 {{ stats.full_entries }} 条，已压缩 {{ stats.compacted_entries }} 条。累计次数不会因清理归零。</p><p v-else>加载历史统计…</p><p v-if="error && !open" role="alert" class="storage-error">{{ error }}</p></div><div class="storage-actions"><el-button :disabled="busy" @click="configure">保留策略</el-button><el-button :loading="busy" @click="cleanup">清理过期详情</el-button></div></section>
  <el-dialog v-model="open" title="自主交易员 · 日记保留策略" width="min(520px,94vw)" :close-on-click-modal="false" :show-close="!busy" :close-on-press-escape="!busy">
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-form label-position="top" @submit.prevent="save"><el-form-item label="完整日记保留天数（0为关闭天数限制）"><el-input-number v-model="draft.days" :min="0" :max="3650" /></el-form-item><el-form-item label="完整日记最多条数（0为关闭条数限制）"><el-input-number v-model="draft.max_entries" :min="0" :max="100000" :step="100" /></el-form-item><el-form-item label="清理检查间隔（小时）"><el-input-number v-model="draft.cleanup_hours" :min="1" :max="168" /></el-form-item></el-form>
    <p class="storage-note">超过天数或条数的旧详细上下文会分批压缩。当天、运行中及最近40次完整日记始终保留；成交账本、账户、报告与防重复运行凭据不清理。此设置不改变交易算法或提示词。</p>
    <template #footer><el-button :disabled="busy" @click="open = false">取消</el-button><el-button type="primary" :loading="busy" @click="save">保存策略</el-button></template>
  </el-dialog>
</template>
<style scoped>
.guardian-storage { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:20px; border-top:1px solid var(--line); padding:28px 0 16px; margin-top:28px; }.guardian-storage h3 { margin:0 0 12px; font-size:14px; font-weight:600; }.guardian-storage p { font-size:12px; line-height:1.8; margin:5px 0; }.storage-note { color:var(--muted); line-height:1.9; font-size:12px; }.storage-error { color:var(--el-color-danger); }.storage-actions { display:flex; }.el-form { margin-top:24px; }
</style>
