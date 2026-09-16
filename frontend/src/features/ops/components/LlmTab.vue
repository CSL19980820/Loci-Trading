<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'

import {
  deleteProvider,
  getProviders,
  refreshProviderModels,
  saveProvider,
  setDefaultProvider,
  testProvider,
} from '@/shared/api/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { confirmDangerous } from '@/shared/lib/confirm'
import type { LlmProvider } from '@/shared/types/quant'
import type { ReceiptPair } from './SettingsPanel.vue'
import LlmModelCatalogDrawer from './LlmModelCatalogDrawer.vue'
import LlmProviderCard from './LlmProviderCard.vue'
import LlmProviderDialog, { type ProviderFormPayload } from './LlmProviderDialog.vue'
import SettingsPanel from './SettingsPanel.vue'
import { useOpsFeedback } from '../composables/useOpsFeedback'

const emit = defineEmits<{
  'providers-loaded': [providers: LlmProvider[]]
  changed: []
}>()

const { busy, notice, errorText, guard } = useOpsFeedback()

const providers = ref<LlmProvider[]>([])
const dialogOpen = ref(false)
const editing = ref<LlmProvider | null>(null)
const catalogOpen = ref(false)
const catalogProvider = ref<LlmProvider | null>(null)
let active = true
let loadVersion = 0

const receipt = computed((): ReceiptPair[] => {
  const def = providers.value.find((p) => p.is_default)
  const keyed = providers.value.filter((p) => p.key_last4).length
  return [
    { key: '在册', value: providers.value.length ? `${providers.value.length} 家` : '0 家' },
    { key: '默认', value: def ? `${def.name} / ${def.default_model || '—'}` : '—' },
    { key: '密钥', value: keyed ? `${keyed} 已设` : '未设' },
  ]
})

function catalogCount(row: LlmProvider): number {
  return row.model_catalog?.length ?? row.models.length
}

function openCreate(): void {
  editing.value = null
  dialogOpen.value = true
}

function openEdit(row: LlmProvider): void {
  editing.value = row
  dialogOpen.value = true
}

function openCatalog(row: LlmProvider): void {
  catalogProvider.value = row
  catalogOpen.value = true
}

async function load(): Promise<void> {
  const version = ++loadVersion
  const rows = await getProviders()
  if (!active || version !== loadVersion) return
  providers.value = rows
  emit('providers-loaded', providers.value)
}

function markRefreshFailed(): void {
  const cause = errorText.value
  errorText.value = `操作已成功，但列表刷新失败；当前列表仍为上次成功加载的数据${cause ? `：${cause}` : ''}`
}

async function writeAndRefresh<T>(write: () => Promise<T>): Promise<T | null> {
  let wrote = false
  const result = await guard(async () => {
    const saved = await write()
    wrote = true
    await load()
    return saved
  })
  if (result === null && wrote) markRefreshFailed()
  return result
}

async function refreshAfterExternalWrite(): Promise<boolean> {
  const refreshed = await guard(async () => {
    await load()
    return true
  })
  if (!refreshed) markRefreshFailed()
  return Boolean(refreshed)
}

async function onSave(payload: ProviderFormPayload): Promise<void> {
  const saved = await writeAndRefresh(() =>
    saveProvider({
      name: payload.name,
      base_url: payload.base_url,
      api_key: payload.api_key,
      protocol: payload.protocol,
      model: payload.model,
      proxy_url: payload.proxy_url,
      note: payload.note,
      validate_key: payload.validate_key,
      discover_models: payload.discover_models,
      is_default: payload.is_default,
    }),
  )
  if (!saved) return
  const n = catalogCount(saved)
  notice.value = `已保存 ${saved.name}，目录 ${n} 个模型`
  dialogOpen.value = false
  editing.value = null
  emit('changed')
  if (!payload.validate_key || !payload.discover_models) return
  openCatalog(saved)
}

async function makeDefaultProvider(name: string): Promise<void> {
  const saved = await writeAndRefresh(() => setDefaultProvider(name))
  if (saved) {
    notice.value = `已将 ${name} 设为默认 LLM 供应商`
    emit('changed')
  }
}

async function pullModels(name: string): Promise<void> {
  const result = await writeAndRefresh(() => refreshProviderModels(name))
  if (result) {
    notice.value = `${name} 已拉取 ${result.count} 个模型`
    emit('changed')
  }
}

async function testProviderRequest(name: string): Promise<void> {
  const result = await guard(() => testProvider(name))
  if (result) {
    notice.value = `${result.provider} · ${result.model} · ${result.latency_ms} ms`
  }
}

async function testFromDialog(): Promise<void> {
  if (!editing.value) return
  await testProviderRequest(editing.value.name)
}

function openCatalogFromDialog(): void {
  if (!editing.value) return
  openCatalog(editing.value)
}

async function onCatalogSaved(saved: LlmProvider): Promise<void> {
  if (!(await refreshAfterExternalWrite())) return
  emit('changed')
  notice.value = `${saved.name} 模型目录已更新`
  if (editing.value?.name === saved.name) editing.value = saved
}

async function confirmDropProvider(name: string): Promise<void> {
  if (!(await confirmDangerous(`确定删除 LLM 供应商「${name}」？`, '确认删除', '删除'))) return
  if (!(await writeAndRefresh(() => deleteProvider(name)))) return
  if (editing.value?.name === name) {
    dialogOpen.value = false
    editing.value = null
  }
  notice.value = `已删除 ${name}`
  emit('changed')
}

defineExpose({ load, providers })

onUnmounted(() => {
  active = false
  loadVersion += 1
})
</script>

<template>
  <SettingsPanel title="LLM 供应商" :receipt="receipt" fill>
    <template #action>
      <el-button type="primary" :disabled="busy" @click="openCreate">+ 添加供应商</el-button>
    </template>

    <div v-if="providers.length" class="provider-grid">
      <LlmProviderCard
        v-for="row in providers"
        :key="row.id"
        :provider="row"
        :busy="busy"
        @edit="openEdit(row)"
        @set-default="makeDefaultProvider(row.name)"
        @catalog="openCatalog(row)"
        @pull="pullModels(row.name)"
        @test="testProviderRequest(row.name)"
        @remove="confirmDropProvider(row.name)"
      />
    </div>
    <EmptyState v-else description="还没有 AI 线路">
      <el-button type="primary" @click="openCreate">添加供应商</el-button>
    </EmptyState>
  </SettingsPanel>

  <LlmProviderDialog
    v-model:open="dialogOpen"
    :provider="editing"
    :busy="busy"
    @save="onSave"
    @test="testFromDialog"
    @catalog="openCatalogFromDialog"
  />

  <LlmModelCatalogDrawer
    v-model:open="catalogOpen"
    :provider="catalogProvider"
    @saved="onCatalogSaved"
  />
</template>

<style scoped>
.provider-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,18rem),1fr)); align-content:start; gap:var(--gap-2); min-width:0; min-height:0; overflow:auto; overscroll-behavior:contain; padding:var(--gap-3); }
</style>
