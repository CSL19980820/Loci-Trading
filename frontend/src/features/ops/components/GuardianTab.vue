<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Setting, Refresh, VideoPlay, VideoPause, Compass } from '@element-plus/icons-vue'
import { getGuardian, saveGuardian } from '@/shared/api/guardian'
import { getProviders } from '@/shared/api/quant'
import type { GuardianStatus, GuardianConfig } from '@/shared/types/guardian'
import type { LlmProvider } from '@/shared/types/quant'
import GuardianSettingsDrawer from './GuardianSettingsDrawer.vue'
import GuardianAccountPanel from './GuardianAccountPanel.vue'
const GuardianReviewPanel = defineAsyncComponent(() => import('./GuardianReviewPanel.vue'))
const GuardianConsultPanel = defineAsyncComponent(() => import('./GuardianConsultPanel.vue'))
const GuardianResearchPanel = defineAsyncComponent(() => import('./GuardianResearchPanel.vue'))

const props = withDefaults(defineProps<{ active?: boolean }>(), { active: true })
const data = shallowRef<GuardianStatus | null>(null)
const providers = shallowRef<LlmProvider[]>([])
const providersLoading = ref(false)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const settingsOpen = ref(false)
const startOnSave = ref(false)
const settings = ref<InstanceType<typeof GuardianSettingsDrawer> | null>(null)
const section = ref('account')
const active = computed(() => props.active)
const enabled = computed(() => data.value?.config.enabled ?? false)
const configured = computed(() => Boolean(data.value?.config.model && data.value.config.provider))
const allocation = computed(() => data.value?.state.equity_cents ? data.value.state.market_value_cents / data.value.state.equity_cents * 100 : 0)
const stateLabel = computed(() => data.value?.notification_silence ? data.value.notification_silence === 'market_closed' ? '休市静默' : '日历待核验' : data.value?.runs[0]?.status === 'running' ? '正在研判' : !configured.value ? '等待配置' : enabled.value ? '运行中' : '已暂停')
const emit = defineEmits<{ summary: [value: { tail: string; state: 'ok' | 'idle' | 'bad' }] }>()
let controller: AbortController | undefined
let pending: Promise<void> | undefined
let providerVersion = 0
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
function accept(value: GuardianStatus): void {
  data.value = value
  emit('summary', { tail: value.config.enabled ? '运行中' : '已暂停', state: value.config.enabled ? 'ok' : 'idle' })
}
async function load(): Promise<void> {
  if (!props.active || disposed || busy.value) return
  // 父页刷新、手动刷新与轮询共用进行中的读取，避免反复取消首屏请求。
  if (pending && !controller?.signal.aborted) return pending
  const request = new AbortController(); controller = request
  loading.value = true
  pending = (async () => {
    try {
      const status = await getGuardian(request.signal)
      if (!disposed && !request.signal.aborted) { accept(status); error.value = '' }
    } catch (e) { if (!disposed && !request.signal.aborted) error.value = e instanceof Error ? e.message : String(e) }
    finally { if (controller === request) { loading.value = false; pending = undefined } }
  })()
  return pending
}
async function configure(start = false): Promise<void> {
  startOnSave.value = start; settingsOpen.value = true; error.value = ''
  const version = ++providerVersion
  providersLoading.value = true
  try {
    const list = await getProviders()
    if (!disposed && version === providerVersion) providers.value = list.filter(p => p.is_active)
  } catch (e) { if (!disposed && version === providerVersion) error.value = e instanceof Error ? e.message : String(e) }
  finally { if (version === providerVersion) providersLoading.value = false }
}
async function save(config: GuardianConfig): Promise<void> {
  controller?.abort()
  busy.value = true; error.value = ''
  try { const result = await saveGuardian(config); if (!disposed) { accept(result); settingsOpen.value = false; ElMessage.success('交易员配置已保存') } }
  catch (e) { if (!disposed) error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
function toggle(): void {
  if (!data.value) return
  if (!configured.value && !enabled.value) { void configure(true); return }
  void save({ ...data.value.config, enabled: !enabled.value })
}
async function poll(): Promise<void> {
  if (disposed) return
  if (props.active && data.value && !busy.value && !loading.value && !settingsOpen.value && !document.hidden) await load()
  if (!disposed) timer = setTimeout(poll, 10000)
}
watch(() => props.active, active => { if (!active) { controller?.abort(); providerVersion++; providersLoading.value = false } })
onMounted(() => { timer = setTimeout(poll, 10000) })
onUnmounted(() => { disposed = true; providerVersion++; controller?.abort(); clearTimeout(timer) })
defineExpose({ load, isDirty: () => settings.value?.isDirty() ?? false })
</script>

<template>
  <div class="guardian-workspace" aria-label="自主交易员">
    <header class="guardian-header">
      <div class="guardian-identity"><span class="guardian-symbol"><el-icon><Compass /></el-icon></span><h2>自主交易员</h2><span class="guardian-state" :class="{ 'is-running': enabled }"><i />{{ stateLabel }}</span></div>
      <div class="guardian-actions"><el-button :icon="Refresh" circle aria-label="刷新交易员" :disabled="busy || loading" @click="load" /><el-button :icon="Setting" :disabled="!data || busy" @click="configure()">交易员设置</el-button><el-button :icon="enabled ? VideoPause : VideoPlay" :type="enabled ? 'default' : 'primary'" :loading="busy" :disabled="!data" @click="toggle">{{ enabled ? '暂停交易员' : configured ? '启动交易员' : '配置并开启' }}</el-button></div>
    </header>
    <el-alert v-if="error && !settingsOpen" :title="error" type="error" :closable="false" show-icon><el-button link @click="load">重试加载</el-button></el-alert>
    <el-skeleton v-if="loading && !data" class="guardian-loading" :rows="5" animated />
    <template v-if="data">
      <div class="guardian-context"><span>{{ data.config.model || '尚未选择模型' }}</span><span>交易时段每 5 分钟研判</span><span>持仓 {{ data.state.positions.length }} 只 · 仓位 {{ Number(allocation.toFixed(2)) }}% · 自主观察 {{ data.observation_count ?? 0 }} 只</span></div>
      <el-tabs v-model="section" class="guardian-navigation" aria-label="交易员工作区"><el-tab-pane label="账户与持仓" name="account" /><el-tab-pane label="复盘与计划" name="reviews" /><el-tab-pane label="观察与研判" name="research" /><el-tab-pane label="与交易员沟通" name="consult" /></el-tabs>
      <template v-if="active">
        <GuardianConsultPanel v-if="section === 'consult'" :model="data.config.model" />
        <GuardianAccountPanel v-if="section === 'account'" :account="data.state" />
        <GuardianReviewPanel v-if="section === 'reviews'" :enabled="enabled" @changed="load" />
        <GuardianResearchPanel v-if="section === 'research'" :account="data.state" :enabled="enabled" :notify="data.config.notify" @changed="load" />
      </template>
      <GuardianSettingsDrawer ref="settings" v-model="settingsOpen" :config="data.config" :default-prompt="data.default_prompt" :providers="providers" :providers-loading="providersLoading" :busy="busy" :error="error" :start-on-save="startOnSave" @save="save" />
    </template>
  </div>
</template>
<style scoped src="./GuardianTab.css"></style>
