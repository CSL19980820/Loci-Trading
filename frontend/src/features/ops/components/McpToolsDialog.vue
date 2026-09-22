<script setup lang="ts">
import { toast } from 'vue-sonner'
import { default as DialogPanel } from '@/shared/components/ui/app/DialogPanel.vue'
import { StatusBadge } from '@/shared/components/ui/app/presentation'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'
import { default as HintTooltip } from '@/shared/components/ui/app/HintTooltip.vue'

import { computed, onUnmounted, ref, watch } from 'vue'


import { getMcpServers, probeMcpServer, refreshMcpTools, type McpProbeResult } from '@/shared/api/quant'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import { toErrorMessage } from '@/shared/lib/errors'
import { dialogWidth } from '@/shared/lib/format'
import type { McpServer, McpToolRow } from '@/shared/types/quant'

type ProbeTone = 'idle' | 'ok' | 'warn' | 'bad' | 'busy'

type ProbeCell = {
  tone: ProbeTone
  label: string
  detail: string
}

const open = defineModel<boolean>({ required: true })

const props = defineProps<{
  server: McpServer | null
}>()

const emit = defineEmits<{ refreshed: [] }>()

const live = ref<McpServer | null>(null)
const probingServer = ref(false)
const refreshingTools = ref(false)
const serverProbe = ref<ProbeCell | null>(null)
let active = true
let session = 0

const current = computed(() => live.value ?? props.server)

function catalogRows(server: McpServer | null): McpToolRow[] {
  if (!server) return []
  if (server.builtin && server.tools_catalog?.length) return server.tools_catalog
  return server.tools
}

const isBuiltin = computed(() => Boolean(current.value?.builtin))
const laneTools = computed(() =>
  catalogRows(current.value).filter(
    (t) => (t.group ?? 'lane') !== 'akshare' && !t.name.startsWith('ak_'),
  ),
)
const akshareTools = computed(() =>
  catalogRows(current.value).filter((t) => t.group === 'akshare' || t.name.startsWith('ak_')),
)
const flatTools = computed(() => catalogRows(current.value))
const laneRows = computed(() => laneTools.value as unknown as Record<string, unknown>[])
const akshareRows = computed(() => akshareTools.value as unknown as Record<string, unknown>[])
const flatRows = computed(() => flatTools.value as unknown as Record<string, unknown>[])

const toolColumns: BasicTableColumn[] = [
  { prop: 'name', label: '工具', minWidth: 140, align: 'center', headerAlign: 'center', slotName: 'name' },
  { prop: 'description', label: '说明', minWidth: 160, align: 'center', headerAlign: 'center', slotName: 'description' },
]

function resetProbes(): void {
  serverProbe.value = null
}

function isCurrent(version: number): boolean {
  return active && open.value && version === session
}

async function syncLiveServer(visible: boolean): Promise<void> {
  const version = ++session
  if (!visible) {
    live.value = null
    probingServer.value = false
    resetProbes()
    return
  }
  resetProbes()
  probingServer.value = false
  live.value = props.server
  const name = props.server?.name
  if (name) {
    try {
      const rows = await getMcpServers()
      if (isCurrent(version)) live.value = rows.find((r) => r.name === name) ?? props.server
    } catch {
      /* 用打开时的快照 */
    }
  }
}

watch([open, () => props.server?.name], ([visible]) => {
  void syncLiveServer(visible)
})

function cellFromResult(result: McpProbeResult): ProbeCell {
  if (!result.ok) {
    return {
      tone: 'bad',
      label: '失败',
      detail: result.error || '探测失败',
    }
  }
  return {
    tone: 'ok',
    label: `通 ${result.rtt_ms}ms`,
    detail: `工具 ${result.tool_count ?? result.tools_updated ?? 0} 个`,
  }
}

function tagType(tone: ProbeTone): 'success' | 'warning' | 'danger' | 'info' {
  if (tone === 'ok') return 'success'
  if (tone === 'warn') return 'warning'
  if (tone === 'bad') return 'danger'
  return 'info'
}

async function refreshToolsList(): Promise<void> {
  const version = session
  const name = current.value?.name
  if (!name || refreshingTools.value || !isCurrent(version)) return
  refreshingTools.value = true
  try {
    await refreshMcpTools(name)
    const rows = await getMcpServers()
    if (!isCurrent(version)) return
    live.value = rows.find((r) => r.name === name) ?? live.value
    toast.success(`已刷新 ${name} 工具列表`)
    emit('refreshed')
  } catch (caught: unknown) {
    if (!isCurrent(version)) return
    toast.error(toErrorMessage(caught, '没刷出工具，确认这台服务还开着'))
  } finally {
    if (isCurrent(version)) refreshingTools.value = false
  }
}

async function probeServer(): Promise<void> {
  const version = session
  const name = current.value?.name
  if (!name || probingServer.value || !isCurrent(version)) return
  probingServer.value = true
  serverProbe.value = { tone: 'busy', label: '探测中', detail: '' }
  try {
    const result = await probeMcpServer(name)
    if (!isCurrent(version)) return
    serverProbe.value = cellFromResult(result)
    if (result.ok) {
      toast.success(`${name} 连通 · ${result.rtt_ms} ms · 工具 ${result.tool_count ?? 0}`)
      const rows = await getMcpServers()
      if (!isCurrent(version)) return
      live.value = rows.find((r) => r.name === name) ?? live.value
      emit('refreshed')
    } else {
      toast.error(result.error || '没探通，确认地址与 Key 仍有效')
    }
  } catch (caught: unknown) {
    if (!isCurrent(version)) return
    const msg = toErrorMessage(caught, '没探通，确认地址与 Key 仍有效')
    serverProbe.value = { tone: 'bad', label: '失败', detail: msg }
    toast.error(msg)
  } finally {
    if (isCurrent(version)) probingServer.value = false
  }
}

onUnmounted(() => {
  active = false
  session += 1
})
</script>

<template>
  <DialogPanel
    v-model="open"
    align-center
    destroy-on-close
    class="mcp-tools-dialog ops-dialog"
    append-to-body
    :width="dialogWidth()"
  >
    <template #header="{ titleId, titleClass }">
      <div class="mcp-tools-head">
        <h4 :id="titleId" :class="titleClass">
          {{ current ? `工具 · ${current.name}` : '工具详情' }}
        </h4>
        <div class="mcp-tools-head__actions">
          <StatusBadge
            v-if="serverProbe"
            size="small"
            effect="light"
            :tone="tagType(serverProbe.tone)"
            class="probe-tag"
            :title="serverProbe.detail"
          >
            {{ serverProbe.label }}
          </StatusBadge>
          <ActionButton
            size="small"
            :busy="refreshingTools"
            :disabled="isBuiltin && !current?.resident"
            @click="refreshToolsList"
          >
            刷新工具
          </ActionButton>
          <!-- 「只验握手、不执行工具」原来是正文里的一段常驻说明，挪到它解释的那颗按钮上 -->
          <HintTooltip placement="bottom-end" content="只验握手与工具发现，不执行工具">
            <ActionButton
              size="small"
              :busy="probingServer"
              @click="probeServer"
            >
              测连通
            </ActionButton>
          </HintTooltip>
        </div>
      </div>
    </template>

    <div class="mcp-tools-body">
      <template v-if="isBuiltin">
        <section class="mcp-detail-group">
          <!-- 两组同屏并列，标题必须留；压成一行：标题 + 计数 chip，解释进 tooltip -->
          <header class="mcp-detail-group__head">
            <HintTooltip
              placement="bottom-start"
              content="Loci 已支持的全部入口；无源的标「线路停用」"
            >
              <h4>线路工具</h4>
            </HintTooltip>
            <StatusBadge size="small" tone="info" effect="plain" class="group-count">
              {{ laneTools.length }}
            </StatusBadge>
          </header>
          <BasicTable
            :columns="toolColumns"
            :data-source="laneRows"
            :pagination="false"
            stripe
            row-key="name"
            empty-text="这条线路还没报出工具"
            empty-reason="点上方「刷新工具」重新发现一次。"
          >
            <template #name="{ row }">
              <span class="mono" :class="{ dim: row.available === false }">{{ row.name }}</span>
              <StatusBadge
                v-if="row.available === false"
                size="small"
                tone="info"
                effect="plain"
                class="avail-tag"
              >
                线路停用
              </StatusBadge>
            </template>
            <template #description="{ row }">
              <HintTooltip :content="String(row.description || '—')" placement="top" :show-after="150" :disabled="!row.description">
                <span class="desc desc-clip">{{ row.description || '—' }}</span>
              </HintTooltip>
            </template>
          </BasicTable>
        </section>
        <section class="mcp-detail-group">
          <header class="mcp-detail-group__head">
            <HintTooltip placement="bottom-start" content="数据源里已上桌的 AkShare 接口">
              <h4>AkShare 接口</h4>
            </HintTooltip>
            <StatusBadge size="small" tone="info" effect="plain" class="group-count">
              {{ akshareTools.length }}
            </StatusBadge>
          </header>
          <BasicTable
            :columns="toolColumns"
            :data-source="akshareRows"
            :pagination="false"
            stripe
            row-key="name"
            empty-text="还没有接口上桌"
            empty-reason="去工坊「数据源 → 按接口」勾选需要的"
          >
            <template #name="{ row }">
              <span class="mono">{{ row.name }}</span>
            </template>
            <template #description="{ row }">
              <HintTooltip :content="String(row.description || '—')" placement="top" :show-after="150" :disabled="!row.description">
                <span class="desc desc-clip">{{ row.description || '—' }}</span>
              </HintTooltip>
            </template>
          </BasicTable>
        </section>
      </template>

      <template v-else>
        <BasicTable
          :columns="toolColumns"
          :data-source="flatRows"
          :pagination="false"
          stripe
          row-key="name"
          empty-text="这台服务还没报出工具"
          empty-reason="点上方「刷新工具」重新发现一次。"
        >
          <template #name="{ row }">
            <span class="mono">{{ row.name }}</span>
          </template>
          <template #description="{ row }">
            <HintTooltip :content="String(row.description || '—')" placement="top" :show-after="150" :disabled="!row.description">
              <span class="desc desc-clip">{{ row.description || '—' }}</span>
            </HintTooltip>
          </template>
        </BasicTable>
      </template>
    </div>
  </DialogPanel>
</template>

<style scoped>
.mcp-tools-head {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  flex-wrap: wrap;
  min-width: 0;
  padding-right: 1.5rem;
}

.mcp-tools-head h4 {
  margin: 0;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mcp-tools-head__actions {
  margin-left: auto;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
  flex-shrink: 0;
}

.mcp-tools-body {
  min-height: 0;
}

.mcp-detail-group {
  margin-bottom: 1rem;
}

.mcp-detail-group:last-child {
  margin-bottom: 0;
}

/* 组标题恒为一行：标题 + 计数 chip */
.mcp-detail-group__head {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  padding: var(--gap-2) var(--gap-3);
  margin-bottom: var(--gap-2);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--surface-sunken);
}

.mcp-detail-group h4 {
  margin: 0;
  font-size: var(--fs-body);
  font-weight: 600;
  color: var(--ink);
}

.group-count {
  font-family: var(--mono);
}

.desc,
.dim {
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

.avail-tag {
  margin-left: 0.35rem;
  vertical-align: middle;
}

.probe-tag {
  max-width: 7.5rem;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>

<style scoped>
/* 高度受视口限制，滚动只在 body 内发生。 */
.mcp-tools-dialog.dialog-panel {
  display: flex;
  flex-direction: column;
  max-height: min(85vh, 40rem);
  margin-top: 0 !important;
  margin-bottom: 0 !important;
  overflow: hidden;
}

.mcp-tools-dialog :deep(.dialog-panel__header) {
  flex-shrink: 0;
  margin-right: 0;
  padding-bottom: 0.65rem;
}

.mcp-tools-dialog :deep(.dialog-panel__body) {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding-top: 0.35rem;
}

.mcp-tools-dialog :deep(.mcp-tools-table .cell) {
  line-height: 1.35;
}
</style>
<style scoped src="./OpsDialogSurface.css"></style>
