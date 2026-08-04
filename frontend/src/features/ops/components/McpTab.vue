<script setup lang="ts">
import { computed, onUnmounted, reactive, ref } from 'vue'

import {
  deleteMcpServer,
  getMcpServers,
  saveMcpServer,
  toggleMcpServer,
} from '@/shared/api/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { confirmDangerous } from '@/shared/lib/confirm'
import { dialogWidth } from '@/shared/lib/format'
import type { McpServer } from '@/shared/types/quant'
import McpToolsDialog from './McpToolsDialog.vue'
import type { ReceiptPair } from './SettingsPanel.vue'
import SettingsPanel from './SettingsPanel.vue'
import { useOpsFeedback } from '../composables/useOpsFeedback'

const emit = defineEmits<{ changed: [] }>()

const { busy, notice, errorText, guard } = useOpsFeedback()

const mcpServers = ref<McpServer[]>([])
const mcpFormOpen = ref(false)
const mcpForm = reactive({
  name: '',
  url: '',
  token: '',
  note: '',
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

const receipt = computed((): ReceiptPair[] => {
  const inactive = mcpServers.value.filter((s) => !s.is_active).length
  const tools = mcpServers.value.reduce((n, s) => n + toolCount(s), 0)
  const synced = mcpServers.value
    .map((s) => s.tools_synced_at)
    .filter(Boolean)
    .sort()
    .at(-1)
  const pairs: ReceiptPair[] = [
    { key: '在册', value: `${mcpServers.value.length} 台` },
    { key: '停用', value: String(inactive) },
    { key: '工具', value: String(tools) },
  ]
  if (synced) {
    pairs.push({ key: '同步', value: synced.replace('T', ' ').slice(0, 16) })
  }
  return pairs
})

async function load(): Promise<void> {
  const version = ++loadVersion
  const rows = await getMcpServers()
  if (!active || version !== loadVersion) return
  mcpServers.value = rows
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

async function submitMcp(): Promise<void> {
  const saved = await writeAndRefresh(() =>
    saveMcpServer({
      name: mcpForm.name,
      url: mcpForm.url,
      token: mcpForm.token || undefined,
      note: mcpForm.note,
      verify: mcpForm.verify,
    }),
  )
  if (saved) {
    notice.value = `已保存 ${saved.name}，发现 ${saved.tools.length} 个工具`
    mcpFormOpen.value = false
    Object.assign(mcpForm, { name: '', url: '', token: '', note: '', verify: true })
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
  <SettingsPanel title="MCP Server" :receipt="receipt">
    <template #action>
      <el-button type="primary" :disabled="busy" @click="mcpFormOpen = true">添加</el-button>
    </template>

    <el-table v-if="mcpServers.length" :data="mcpServers" size="small" row-key="id">
      <el-table-column label="名称" min-width="120">
        <template #default="{ row }">
          <strong>{{ row.name }}</strong>
          <el-tag v-if="row.builtin" size="small" type="info" class="name-tag">内置</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="描述" min-width="120" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="desc">{{ row.note || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="地址" min-width="140" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="mono dim">{{ row.url || (row.builtin ? '进程内' : '—') }}</span>
        </template>
      </el-table-column>
      <el-table-column label="Token" width="90">
        <template #default="{ row }">
          <span class="mono">{{ row.builtin ? '—' : row.token_last4 || '无' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="工具数" align="center" width="80">
        <template #default="{ row }">
          <span class="mono">{{ toolCount(row) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" align="center" width="80">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small" effect="light">
            {{ row.is_active ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160" fixed="right" align="right">
        <template #default="{ row }">
          <el-button link :disabled="busy" @click="openDetail(row)">详情</el-button>
          <template v-if="!row.builtin">
            <el-button link :disabled="busy" @click="toggleMcp(row)">
              {{ row.is_active ? '停用' : '启用' }}
            </el-button>
            <el-button link type="danger" :disabled="busy" @click="confirmDropMcp(row.name)">
              删除
            </el-button>
          </template>
        </template>
      </el-table-column>
    </el-table>
    <EmptyState v-else description="尚未配置 MCP Server">
      <el-button type="primary" @click="mcpFormOpen = true">添加</el-button>
    </EmptyState>
  </SettingsPanel>

  <el-dialog v-model="mcpFormOpen" title="添加 MCP Server" :width="dialogWidth()" destroy-on-close>
    <el-form label-position="top" @submit.prevent="submitMcp">
      <div class="form-grid">
        <el-form-item label="名称" required>
          <el-input v-model.trim="mcpForm.name" placeholder="my-data-source" />
        </el-form-item>
        <el-form-item label="地址" required class="full-span">
          <el-input v-model.trim="mcpForm.url" placeholder="https://mcp.example.com" />
        </el-form-item>
        <el-form-item label="Token（可选）" class="full-span">
          <el-input
            v-model.trim="mcpForm.token"
            type="password"
            autocomplete="off"
            placeholder="Bearer token"
            show-password
          />
        </el-form-item>
        <el-form-item label="备注" class="full-span">
          <el-input v-model.trim="mcpForm.note" placeholder="用途说明" />
        </el-form-item>
        <el-form-item class="full-span">
          <el-checkbox v-model="mcpForm.verify">保存时握手校验</el-checkbox>
        </el-form-item>
      </div>
    </el-form>
    <template #footer>
      <el-button @click="mcpFormOpen = false">取消</el-button>
      <el-button type="primary" :disabled="busy" @click="submitMcp">保存并发现工具</el-button>
    </template>
  </el-dialog>

  <McpToolsDialog v-model="detailOpen" :server="detailServer" @refreshed="onDetailRefreshed" />
</template>

<style scoped>
.desc {
  color: var(--mist);
}

.dim {
  color: var(--mist);
}

.name-tag {
  margin-left: 0.4rem;
  vertical-align: middle;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 0.75rem;
}

.form-grid .full-span {
  grid-column: 1 / -1;
}
</style>
