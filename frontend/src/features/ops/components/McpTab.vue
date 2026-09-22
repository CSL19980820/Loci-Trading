<script setup lang="ts">
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'
import { default as DialogPanel } from '@/shared/components/ui/app/DialogPanel.vue'
import { default as FormLayout } from '@/shared/components/ui/app/FormLayout.vue'
import { default as FormField } from '@/shared/components/ui/app/FormField.vue'
import { default as TextField } from '@/shared/components/ui/app/TextField.vue'
import { default as DateField } from '@/shared/components/ui/app/DateField.vue'
import { default as CheckboxField } from '@/shared/components/ui/app/CheckboxField.vue'
import { Plug, Plus, Server } from '@lucide/vue'

import { computed, onUnmounted, reactive, ref } from 'vue'

import {
  deleteMcpServer,
  getMcpQuota,
  getMcpServers,
  saveMcpServer,
  toggleMcpServer,
} from '@/shared/api/quant'
import { Button } from '@/shared/components/ui/button'
import { Card, CardAction, CardHeader, CardTitle } from '@/shared/components/ui/card'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import StatCard from '@/shared/components/ui/StatCard.vue'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import { confirmDangerous } from '@/shared/lib/confirm'
import { dialogWidth } from '@/shared/lib/format'
import type { McpQuotaSnapshot, McpServer } from '@/shared/types/quant'
import McpServerRow from './McpServerRow.vue'
import McpToolsDialog from './McpToolsDialog.vue'
import WudaoMcpDialog from './WudaoMcpDialog.vue'
import type { ReceiptPair } from './SettingsPanel.vue'
import SettingsPanel from './SettingsPanel.vue'
import { useOpsFeedback } from '../composables/useOpsFeedback'

const emit = defineEmits<{ changed: [] }>()

const { busy, notice, errorText, guard } = useOpsFeedback()

const mcpServers = ref<McpServer[]>([])
const quotaSnap = ref<McpQuotaSnapshot | null>(null)
const mcpFormOpen = ref(false)
const wudaoOpen = ref(false)

const mcpForm = reactive({
  name: '',
  url: '',
  token: '',
  note: '',
  expires_at: '',
  verify: true,
})
const detailOpen = ref(false)
const detailServer = ref<McpServer | null>(null)
let active = true
let loadVersion = 0

function toolCount(server: McpServer): number {
  if (server.builtin && server.tools_catalog?.length) return server.tools_catalog.length
  return server.tools.length
}

function isResident(server: McpServer): boolean {
  return Boolean(server.resident || (server.builtin && (server.name === 'wudao' || server.name === 'wudao-a-stock')))
}

const builtinServers = computed(() => mcpServers.value.filter((s) => s.builtin))
const externalServers = computed(() => mcpServers.value.filter((s) => !s.builtin))
const wudaoServer = computed(
  () =>
    mcpServers.value.find(
      (s) => s.resident || s.name === 'wudao' || s.name === 'wudao-a-stock',
    ) ?? null,
)

const inactiveCount = computed(() => mcpServers.value.filter((s) => !s.is_active).length)
const totalTools = computed(() => mcpServers.value.reduce((n, s) => n + toolCount(s), 0))

const receipt = computed((): ReceiptPair[] => {
  const pairs: ReceiptPair[] = [
    { key: '在册', value: `${mcpServers.value.length} 台` },
    { key: '停用', value: String(inactiveCount.value) },
    { key: '工具', value: String(totalTools.value) },
  ]
  if (quotaSnap.value) {
    pairs.push({
      key: '调用限额',
      value: `${quotaSnap.value.remaining.total}/${quotaSnap.value.limits.daily_total}`,
    })
  }
  return pairs
})

/** 今日配额用掉的比例（0–100），给读数卡的趟势 chip */
const quotaUsedPct = computed(() => {
  const q = quotaSnap.value
  if (!q || !q.limits.daily_total) return null
  return Math.round((q.used.total / q.limits.daily_total) * 100)
})

async function load(): Promise<void> {
  const version = ++loadVersion
  const [rows, quota] = await Promise.all([getMcpServers(), getMcpQuota().catch(() => null)])
  if (!active || version !== loadVersion) return
  mcpServers.value = Array.isArray(rows) ? rows : []
  quotaSnap.value = quota
}

function markRefreshFailed(): void {
  notice.value = ''
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

function openWudaoConfig(): void {
  wudaoOpen.value = true
}

async function submitMcp(): Promise<void> {
  const saved = await writeAndRefresh(() =>
    saveMcpServer({
      name: mcpForm.name,
      url: mcpForm.url,
      token: mcpForm.token || undefined,
      note: mcpForm.note,
      expires_at: mcpForm.expires_at || undefined,
      verify: mcpForm.verify,
    }),
  )
  if (saved) {
    notice.value = saved.tools.length
      ? `已保存 ${saved.name}，发现 ${saved.tools.length} 个工具`
      : `已保存 ${saved.name}；这次没发现工具，可在「详情」里点「刷新工具」再试一次`
    mcpFormOpen.value = false
    Object.assign(mcpForm, {
      name: '',
      url: '',
      token: '',
      note: '',
      expires_at: '',
      verify: true,
    })
    emit('changed')
  }
}

async function toggleMcp(item: McpServer): Promise<void> {
  if (!(await writeAndRefresh(() => toggleMcpServer(item.name, !item.is_active)))) return
  emit('changed')
}

async function confirmDropMcp(name: string): Promise<void> {
  if (!(await confirmDangerous(`确定删除 MCP Server「${name}」？`, '确认删除', '删除'))) return
  if (!(await writeAndRefresh(() => deleteMcpServer(name)))) return
  notice.value = `已删除 ${name}`
  emit('changed')
}

function openDetail(item: McpServer): void {
  detailServer.value = item
  detailOpen.value = true
}

async function onDetailRefreshed(): Promise<void> {
  if (!(await refreshAfterExternalWrite())) return
  if (detailServer.value) {
    detailServer.value =
      mcpServers.value.find((s) => s.name === detailServer.value?.name) ?? detailServer.value
  }
  emit('changed')
}

defineExpose({ load })

onUnmounted(() => {
  active = false
  loadVersion += 1
})
</script>

<template>
  <SettingsPanel
    title="工具连接"
    :receipt="receipt"
  >
    <template #action>
      <Button v-if="wudaoServer" variant="outline" size="sm" :disabled="busy" @click="openWudaoConfig">
        <Plug />
        配置悟道
      </Button>
      <Button size="sm" :disabled="busy" @click="mcpFormOpen = true">
        <Plus />
        添加外部 MCP
      </Button>
    </template>

    <div class="stat-strip stat-strip--plain cols-3 mcp-stats">
      <StatCard label="在册服务" :value="mcpServers.length" :hint="inactiveCount ? `${inactiveCount} 台停用` : '全部启用'">
        <template #icon><Server /></template>
      </StatCard>
      <StatCard label="可调用工具" :value="totalTools" hint="含内置工具" />
      <StatCard
        label="今日调用剩余"
        :value="quotaSnap ? quotaSnap.remaining.total : '—'"
        :hint="quotaSnap ? `已用 ${quotaUsedPct ?? 0}%` : '未接常驻线路'"
      />
    </div>

    <Card class="mcp-card">
      <CardHeader class="mcp-card__head">
        <CardTitle>内置服务</CardTitle>
      </CardHeader>
      <div v-if="builtinServers.length" class="mcp-list">
        <McpServerRow
          v-for="row in builtinServers"
          :key="row.id || row.name"
          :server="row"
          :busy="busy"
          :resident="isResident(row)"
          @detail="openDetail(row)"
          @configure="openWudaoConfig"
          @toggle="toggleMcp(row)"
          @remove="confirmDropMcp(row.name)"
        />
      </div>
      <EmptyState
        v-else
        compact
        description="尚未接入内置 MCP"
        reason="内置服务会在启动后出现在这里"
      />
    </Card>

    <Card class="mcp-card">
      <CardHeader class="mcp-card__head">
        <CardTitle class="inline-flex items-center gap-2">
          外部 MCP
          <UiBadge variant="secondary">{{ externalServers.length }}</UiBadge>
        </CardTitle>
        <CardAction>
          <Button variant="outline" size="sm" :disabled="busy" @click="mcpFormOpen = true">
            <Plus />
            添加
          </Button>
        </CardAction>
      </CardHeader>
      <div v-if="externalServers.length" class="mcp-list">
        <McpServerRow
          v-for="row in externalServers"
          :key="row.id || row.name"
          :server="row"
          :busy="busy"
          @detail="openDetail(row)"
          @toggle="toggleMcp(row)"
          @remove="confirmDropMcp(row.name)"
        />
      </div>
      <EmptyState
        v-else
        description="还没有外部 MCP"
        reason="接入一台远端服务，助手就能用上它的工具"
        :icon="Plug"
        class="mcp-empty"
      >
        <Button size="sm" :disabled="busy" @click="mcpFormOpen = true">添加外部 MCP</Button>
      </EmptyState>
    </Card>
  </SettingsPanel>

  <DialogPanel v-model="mcpFormOpen" class="ops-dialog" title="添加 MCP Server" :width="dialogWidth()" destroy-on-close>
    <FormLayout
      class="form-grid"
      label-position="top"
      size="small"
      @submit.prevent="submitMcp"
    >
      <FormField label="名称" required>
        <TextField v-model.trim="mcpForm.name" placeholder="my-data-source" />
      </FormField>
      <FormField label="地址" required class="full-span">
        <TextField v-model.trim="mcpForm.url" placeholder="https://mcp.example.com" />
      </FormField>
      <FormField label="Token" required class="full-span">
        <TextField
          v-model.trim="mcpForm.token"
          type="password"
          autocomplete="off"
          placeholder="开发者页复制的 API Key（lb_ 开头）"
          show-password
        />
      </FormField>
      <FormField label="到期日（可选）" class="full-span">
        <DateField
          v-model="mcpForm.expires_at"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="套餐到期后自动跳过"
          style="width: 100%"
        />
      </FormField>
      <FormField label="备注" class="full-span">
        <TextField v-model.trim="mcpForm.note" placeholder="用途说明" />
      </FormField>
      <FormField class="full-span">
        <CheckboxField v-model="mcpForm.verify">保存时握手校验</CheckboxField>
      </FormField>
    </FormLayout>
    <template #footer>
      <ActionButton @click="mcpFormOpen = false">取消</ActionButton>
      <ActionButton tone="primary" :disabled="busy" @click="submitMcp">保存并发现工具</ActionButton>
    </template>
  </DialogPanel>

  <McpToolsDialog v-model="detailOpen" :server="detailServer" @refreshed="onDetailRefreshed" />
  <WudaoMcpDialog v-model="wudaoOpen" :server="wudaoServer" @saved="() => writeAndRefresh(async () => true)" />
</template>

<style scoped>
.mcp-stats {
  margin-bottom: 0;
}

.mcp-card {
  gap: 0;
  padding: 0;
  overflow: hidden;
}

.mcp-card__head {
  padding: var(--gap-4) var(--gap-4) var(--gap-3);
  border-bottom: 1px solid var(--border-subtle);
}

.mcp-list {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.mcp-empty {
  padding: var(--gap-6) var(--gap-4);
}
</style>
<style scoped src="./OpsDialogSurface.css"></style>
