<script setup lang="ts">
import { computed, onUnmounted, reactive, ref } from 'vue'

import {
  deleteMcpServer,
  getMcpQuota,
  getMcpServers,
  saveMcpServer,
  toggleMcpServer,
} from '@/shared/api/quant'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import { confirmDangerous } from '@/shared/lib/confirm'
import { dialogWidth } from '@/shared/lib/format'
import type { McpQuotaSnapshot, McpServer } from '@/shared/types/quant'
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

const builtinServers = computed(() => mcpServers.value.filter((s) => s.builtin))
const externalServers = computed(() => mcpServers.value.filter((s) => !s.builtin))
const wudaoServer = computed(
  () =>
    mcpServers.value.find(
      (s) => s.resident || s.name === 'wudao' || s.name === 'wudao-a-stock',
    ) ?? null,
)

const receipt = computed((): ReceiptPair[] => {
  const inactive = mcpServers.value.filter((s) => !s.is_active).length
  const tools = mcpServers.value.reduce((n, s) => n + toolCount(s), 0)
  const pairs: ReceiptPair[] = [
    { key: '在册', value: `${mcpServers.value.length} 台` },
    { key: '停用', value: String(inactive) },
    { key: '工具', value: String(tools) },
  ]
  if (quotaSnap.value) {
    pairs.push({
      key: '配额',
      value: `${quotaSnap.value.remaining.total}/${quotaSnap.value.limits.daily_total}`,
    })
  }
  return pairs
})

const builtinRows = computed(() => builtinServers.value as unknown as Record<string, unknown>[])
const externalRows = computed(() => externalServers.value as unknown as Record<string, unknown>[])

const builtinColumns: BasicTableColumn[] = [
  { prop: 'name', label: '名称', minWidth: 120, slotName: 'name' },
  { prop: 'note', label: '描述', minWidth: 120, slotName: 'note' },
  { prop: 'url', label: '地址', minWidth: 140, slotName: 'url' },
  { prop: 'token_last4', label: 'Token', width: 90, slotName: 'token' },
  { prop: 'expires_at', label: '到期', width: 108, slotName: 'expires' },
  { prop: 'tools', label: '工具数', width: 80, align: 'center', headerAlign: 'center', slotName: 'tools' },
  { prop: 'is_active', label: '状态', minWidth: 96, align: 'center', headerAlign: 'center', slotName: 'status' },
  { prop: 'id', label: '操作', width: 160, fixed: 'right', align: 'center', headerAlign: 'center', slotName: 'actions' },
]

const externalColumns: BasicTableColumn[] = [
  { prop: 'name', label: '名称', minWidth: 120, slotName: 'name' },
  { prop: 'url', label: '地址', minWidth: 140, slotName: 'url' },
  { prop: 'tools', label: '工具数', width: 80, align: 'center', headerAlign: 'center', slotName: 'tools' },
  { prop: 'id', label: '操作', width: 160, fixed: 'right', align: 'center', headerAlign: 'center', slotName: 'actions' },
]

function asServer(row: Record<string, unknown>): McpServer {
  return row as unknown as McpServer
}

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

function serverStatus(row: McpServer): { label: string; type: 'success' | 'info' | 'warning' | 'danger' } {
  if (row.resident || (row.builtin && (row.name === 'wudao' || row.name === 'wudao-a-stock'))) {
    if (!row.is_active) return { label: '停用', type: 'info' }
    if (row.is_usable === false) return { label: row.skip_reason || '未配置', type: 'warning' }
    return { label: '已连接', type: 'success' }
  }
  if (row.builtin) return { label: '内置', type: 'info' }
  if (!row.is_active) return { label: '停用', type: 'info' }
  if (row.is_usable === false) return { label: row.skip_reason || '不可用', type: 'warning' }
  return { label: '可用', type: 'success' }
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
  <SettingsPanel title="MCP Server" :receipt="receipt" fill>
    <template #action>
      <el-button v-if="wudaoServer" :disabled="busy" @click="openWudaoConfig">配置悟道</el-button>
    </template>

    <BasicTable
      class="mb"
      :columns="builtinColumns"
      :data-source="builtinRows"
      :pagination="false"
      :loading="busy && !mcpServers.length"
      row-key="id"
      stripe
      empty-text="尚未接入内置 MCP"
      empty-reason="内置服务会在启动后出现在这里"
    >
      <template #name="{ row }">
        <strong>{{ row.name }}</strong>
        <el-tag v-if="row.builtin" size="small" type="info" effect="plain" class="name-tag">内置</el-tag>
        <el-tag v-if="row.resident" size="small" type="warning" effect="plain" class="name-tag">常驻</el-tag>
      </template>
      <template #note="{ row }">
        <el-tooltip :content="String(row.note || '—')" placement="top" :show-after="150" :disabled="!row.note">
          <span class="desc desc-clip">{{ row.note || '—' }}</span>
        </el-tooltip>
      </template>
      <template #url="{ row }">
        <el-tooltip :content="String(row.url || (row.builtin ? '进程内' : '—'))" placement="top" :show-after="150">
          <span class="mono dim desc-clip">{{ row.url || (row.builtin ? '进程内' : '—') }}</span>
        </el-tooltip>
      </template>
      <template #token="{ row }">
        <span class="mono">{{ row.resident ? row.token_last4 || '无' : row.builtin ? '—' : row.token_last4 || '无' }}</span>
      </template>
      <template #expires="{ row }">
        <span class="mono dim">{{ row.resident ? row.expires_at || '不限' : row.builtin ? '—' : row.expires_at || '不限' }}</span>
      </template>
      <template #tools="{ row }">
        <span class="mono">{{ toolCount(asServer(row)) }}</span>
      </template>
      <template #status="{ row }">
        <el-tag :type="serverStatus(asServer(row)).type" size="small" effect="plain">
          {{ serverStatus(asServer(row)).label }}
        </el-tag>
      </template>
      <template #actions="{ row }">
        <el-button link :disabled="busy" @click="openDetail(asServer(row))">服务详情</el-button>
        <template v-if="row.resident">
          <el-button link :disabled="busy" @click="openWudaoConfig">配置</el-button>
        </template>
        <template v-else-if="!row.builtin">
          <el-button link :disabled="busy" @click="toggleMcp(asServer(row))">
            {{ row.is_active ? '停用' : '启用' }}
          </el-button>
          <el-button link type="danger" :disabled="busy" @click="confirmDropMcp(String(row.name))">
            删除
          </el-button>
        </template>
      </template>
    </BasicTable>

    <div class="ext-head">
      <h4 class="ext-title">外部 MCP</h4>
      <el-tag size="small" type="info" effect="plain" class="ext-count">
        {{ externalServers.length }}
      </el-tag>
      <el-button type="primary" :disabled="busy" @click="mcpFormOpen = true">
        添加外部 MCP
      </el-button>
    </div>
    <BasicTable
      :columns="externalColumns"
      :data-source="externalRows"
      :pagination="false"
      row-key="id"
      stripe
      empty-text="还没有外部 MCP"
      empty-reason="点「添加外部 MCP」接入一台"
    >
      <template #name="{ row }">
        <strong>{{ row.name }}</strong>
      </template>
      <template #url="{ row }">
        <el-tooltip :content="String(row.url || '')" placement="top" :show-after="150">
          <span class="mono dim desc-clip">{{ row.url }}</span>
        </el-tooltip>
      </template>
      <template #tools="{ row }">
        <span class="mono">{{ toolCount(asServer(row)) }}</span>
      </template>
      <template #actions="{ row }">
        <el-button link :disabled="busy" @click="openDetail(asServer(row))">工具详情</el-button>
        <el-button link :disabled="busy" @click="toggleMcp(asServer(row))">
          {{ row.is_active ? '停用' : '启用' }}
        </el-button>
        <el-button link type="danger" :disabled="busy" @click="confirmDropMcp(String(row.name))">
          删除
        </el-button>
      </template>
    </BasicTable>
  </SettingsPanel>

  <el-dialog v-model="mcpFormOpen" class="ops-dialog" title="添加 MCP Server" :width="dialogWidth()" destroy-on-close>
    <el-form
      class="form-grid"
      label-position="right"
      label-width="6.5em"
      size="small"
      @submit.prevent="submitMcp"
    >
      <el-form-item label="名称" required>
        <el-input v-model.trim="mcpForm.name" placeholder="my-data-source" />
      </el-form-item>
      <el-form-item label="地址" required class="full-span">
        <el-input v-model.trim="mcpForm.url" placeholder="https://mcp.example.com" />
      </el-form-item>
      <el-form-item label="Token" required class="full-span">
        <el-input
          v-model.trim="mcpForm.token"
          type="password"
          autocomplete="off"
          placeholder="开发者页复制的 API Key（lb_ 开头）"
          show-password
        />
      </el-form-item>
      <el-form-item label="到期日（可选）" class="full-span">
        <el-date-picker
          v-model="mcpForm.expires_at"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="套餐到期后自动跳过"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item label="备注" class="full-span">
        <el-input v-model.trim="mcpForm.note" placeholder="用途说明" />
      </el-form-item>
      <el-form-item class="full-span">
        <el-checkbox v-model="mcpForm.verify">保存时握手校验</el-checkbox>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="mcpFormOpen = false">取消</el-button>
      <el-button type="primary" :disabled="busy" @click="submitMcp">保存并发现工具</el-button>
    </template>
  </el-dialog>

  <McpToolsDialog v-model="detailOpen" :server="detailServer" @refreshed="onDetailRefreshed" />
  <WudaoMcpDialog v-model="wudaoOpen" :server="wudaoServer" @saved="() => writeAndRefresh(async () => true)" />
</template>

<style scoped>
/* 加载态不再定高：EP 的 v-loading 遮罩自带 spinner，8rem 只是空白 */
.mcp-loading {
  padding: var(--gap-4) 0;
}

.desc {
  color: var(--mist);
}

.desc-clip {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}

.dim {
  color: var(--mist);
}

.name-tag {
  margin-left: var(--gap-1);
  vertical-align: middle;
}

/* 栅格与 .full-span 用全局 .form-grid（style.components.css），不在此另立一套 */

.mb {
  margin-bottom: var(--gap-4);
}

/* 标题 + 计数 chip + 主操作同一行 */
.ext-head {
  display: flex;
  flex-wrap: wrap;
  flex-shrink: 0;
  padding: var(--gap-2) var(--gap-3);
  border-block: 1px solid var(--rule);
  background: var(--surface-sunken);
  align-items: center;
  gap: var(--gap-2);
  margin-bottom: var(--gap-2);
}

.ext-title {
  margin: 0;
  font-size: var(--fs-body);
  color: var(--ink);
}

.ext-count {
  font-family: var(--mono);
}

.ext-head .el-button {
  margin-left: auto;
}
</style>
<style scoped src="./OpsDialogSurface.css"></style>
