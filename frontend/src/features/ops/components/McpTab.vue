<script setup lang="ts">
import { computed, onUnmounted, reactive, ref } from 'vue'

import {
  deleteMcpServer,
  getMcpQuota,
  getMcpServers,
  saveMcpServer,
  toggleMcpServer,
} from '@/shared/api/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
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

async function load(): Promise<void> {
  const version = ++loadVersion
  const [rows, quota] = await Promise.all([getMcpServers(), getMcpQuota().catch(() => null)])
  if (!active || version !== loadVersion) return
  mcpServers.value = rows
  quotaSnap.value = quota
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
  <SettingsPanel title="MCP Server" :receipt="receipt">
    <template #action>
      <el-button v-if="wudaoServer" :disabled="busy" @click="openWudaoConfig">配置悟道</el-button>
    </template>

    <el-table v-if="builtinServers.length" :data="builtinServers" size="small" row-key="id" class="mb">
      <el-table-column label="名称" min-width="120">
        <template #default="{ row }">
          <strong>{{ row.name }}</strong>
          <el-tag v-if="row.builtin" size="small" type="info" class="name-tag">内置</el-tag>
          <el-tag v-if="row.resident" size="small" type="warning" class="name-tag">常驻</el-tag>
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
          <span class="mono">{{ row.resident ? row.token_last4 || '无' : row.builtin ? '—' : row.token_last4 || '无' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="到期" width="108">
        <template #default="{ row }">
          <span class="mono dim">{{ row.resident ? row.expires_at || '不限' : row.builtin ? '—' : row.expires_at || '不限' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="工具数" align="center" width="80">
        <template #default="{ row }">
          <span class="mono">{{ toolCount(row) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" align="center" min-width="96">
        <template #default="{ row }">
          <el-tag :type="serverStatus(row).type" size="small" effect="light">
            {{ serverStatus(row).label }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160" fixed="right" align="center" header-align="center">
        <template #default="{ row }">
          <el-button link :disabled="busy" @click="openDetail(row)">详情</el-button>
          <template v-if="row.resident">
            <el-button link :disabled="busy" @click="openWudaoConfig">配置</el-button>
          </template>
          <template v-else-if="!row.builtin">
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

    <!--
      标题保留但压成功能行：内置表与外部表同屏并列，只靠列差分不清谁是谁。
      「添加外部 MCP」从面板头挪到这里——它加的就是这张表的行，计数也在同一行。
      条件从「有外部服务」放宽到「有任何服务」，否则一台外部都没有时按钮会消失。
    -->
    <div v-if="mcpServers.length" class="ext-head">
      <h4 class="ext-title">外部 MCP</h4>
      <el-tag size="small" type="info" effect="plain" class="ext-count">
        {{ externalServers.length }}
      </el-tag>
      <el-button type="primary" :disabled="busy" @click="mcpFormOpen = true">
        添加外部 MCP
      </el-button>
    </div>
    <el-table v-if="externalServers.length" :data="externalServers" size="small" row-key="id">
      <el-table-column label="名称" min-width="120">
        <template #default="{ row }">
          <strong>{{ row.name }}</strong>
        </template>
      </el-table-column>
      <el-table-column label="地址" min-width="140" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="mono dim">{{ row.url }}</span>
        </template>
      </el-table-column>
      <el-table-column label="工具数" align="center" width="80">
        <template #default="{ row }">
          <span class="mono">{{ toolCount(row) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160" fixed="right" align="center" header-align="center">
        <template #default="{ row }">
          <el-button link :disabled="busy" @click="openDetail(row)">详情</el-button>
          <el-button link :disabled="busy" @click="toggleMcp(row)">
            {{ row.is_active ? '停用' : '启用' }}
          </el-button>
          <el-button link type="danger" :disabled="busy" @click="confirmDropMcp(row.name)">
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <!--
      加载态与真空态要分开：此前两者共用「正在加载 MCP…」，
      一台都没配时会永远停在「正在加载」，看着像卡死。
    -->
    <div v-if="busy && !mcpServers.length" v-loading="true" class="mcp-loading" />
    <EmptyState
      v-else-if="!mcpServers.length"
      description="尚未接入 MCP Server"
      reason="MCP 为助手提供行情、公告等外部工具；内置的 loci-market 会随程序启动。"
    >
      <el-button type="primary" :disabled="busy" @click="mcpFormOpen = true">添加外部 MCP</el-button>
    </EmptyState>
  </SettingsPanel>

  <el-dialog v-model="mcpFormOpen" title="添加 MCP Server" :width="dialogWidth()" destroy-on-close>
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
  align-items: center;
  gap: var(--gap-2);
  margin-bottom: var(--gap-2);
}

.ext-title {
  margin: 0;
  font-size: var(--fs-aux);
  color: var(--muted);
}

.ext-count {
  font-family: var(--mono);
}

.ext-head .el-button {
  margin-left: auto;
}
</style>
