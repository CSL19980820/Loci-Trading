<script setup lang="ts">
import { Ellipsis } from '@lucide/vue'
import { computed } from 'vue'

import { Button } from '@/shared/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/shared/components/ui/dropdown-menu'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import type { McpServer } from '@/shared/types/quant'

/**
 * 一台 MCP Server 的列表行（Linear 式）：
 * 左侧字母方块 + 名称 / 说明两行，中间一串等宽元信息（地址 · Token · 到期），
 * 右侧工具数徽标 + 状态点 + `⋯` 菜单。整行可点进详情；≤640 元信息换到第二行。
 */
const props = defineProps<{
  server: McpServer
  busy?: boolean
  /** 悟道常驻线路：菜单里给「配置」而不是启停 / 删除 */
  resident?: boolean
}>()

const emit = defineEmits<{
  detail: []
  configure: []
  toggle: []
  remove: []
}>()

const initial = computed(() => (props.server.name.slice(0, 1) || '?').toUpperCase())

const toolCount = computed(() => {
  const s = props.server
  if (s.builtin && s.tools_catalog?.length) return s.tools_catalog.length
  return s.tools.length
})

const status = computed((): { label: string; variant: 'ok' | 'warn' | 'secondary' | 'info' } => {
  const row = props.server
  if (props.resident) {
    if (!row.is_active) return { label: '停用', variant: 'secondary' }
    if (row.is_usable === false) return { label: row.skip_reason || '未配置', variant: 'warn' }
    return { label: '已连接', variant: 'ok' }
  }
  if (row.builtin) return { label: '进程内', variant: 'info' }
  if (!row.is_active) return { label: '停用', variant: 'secondary' }
  if (row.is_usable === false) return { label: row.skip_reason || '不可用', variant: 'warn' }
  return { label: '可用', variant: 'ok' }
})

const host = computed(() => {
  const url = props.server.url
  if (!url) return props.server.builtin ? '进程内' : '—'
  try {
    return new URL(url).host
  } catch {
    return url.replace(/^https?:\/\//, '').split('/')[0] || url
  }
})

const tokenLabel = computed(() => {
  const s = props.server
  if (s.builtin && !props.resident) return ''
  return s.token_last4 ? `···${s.token_last4}` : '无 Token'
})

const expiresLabel = computed(() => {
  const s = props.server
  if (s.builtin && !props.resident) return ''
  return s.expires_at ? `到期 ${s.expires_at}` : '不限期'
})
</script>

<template>
  <article
    class="mcp-row"
    :class="{ 'is-off': !server.is_active, 'is-bad': server.is_usable === false && server.is_active }"
    role="button"
    tabindex="0"
    :aria-label="`${server.name} · 服务详情`"
    @click="emit('detail')"
    @keydown.enter.self.prevent="emit('detail')"
    @keydown.space.self.prevent="emit('detail')"
  >
    <span class="mcp-row__mark" aria-hidden="true">{{ initial }}</span>
    <div class="mcp-row__identity">
      <div class="mcp-row__title">
        <strong class="mcp-row__name">{{ server.name }}</strong>
        <UiBadge v-if="resident" variant="default">常驻</UiBadge>
        <UiBadge v-else-if="server.builtin" variant="secondary">内置</UiBadge>
        <UiBadge :variant="status.variant" dot class="mcp-row__status">{{ status.label }}</UiBadge>
      </div>
      <p class="mcp-row__meta-line" :title="server.note || server.url">{{ host }}<template v-if="tokenLabel"> · {{ tokenLabel }}</template><template v-if="expiresLabel"> · {{ expiresLabel }}</template><template v-if="server.note"> · {{ server.note }}</template></p>
    </div>
    <div class="mcp-row__tail" @click.stop>
      <span class="mcp-row__tools" :title="`${toolCount} 个工具`">{{ toolCount }}<small>工具</small></span>
      <DropdownMenu>
        <DropdownMenuTrigger as-child>
          <Button variant="ghost" size="icon-sm" :disabled="busy" :aria-label="`${server.name} 的操作`">
            <Ellipsis />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem @select="emit('detail')">服务详情</DropdownMenuItem>
          <DropdownMenuItem v-if="resident" @select="emit('configure')">配置</DropdownMenuItem>
          <template v-else-if="!server.builtin">
            <DropdownMenuItem @select="emit('toggle')">{{ server.is_active ? '停用' : '启用' }}</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" @select="emit('remove')">删除</DropdownMenuItem>
          </template>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  </article>
</template>

<style scoped>
.mcp-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--gap-3);
  min-height: 52px;
  padding: var(--gap-2) var(--gap-3) var(--gap-2) var(--gap-4);
  border-top: 1px solid var(--border-subtle);
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease);
}

.mcp-row:first-child {
  border-top: 0;
}

.mcp-row:hover {
  background: var(--surface-hover);
}

.mcp-row:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: -2px;
  border-radius: var(--radius-sm);
}

.mcp-row__mark {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  background: var(--surface-sunken);
  color: var(--text-secondary);
  font-family: var(--mono);
  font-size: var(--fs-ui);
  font-weight: 600;
}

.mcp-row.is-off .mcp-row__mark {
  color: var(--text-disabled);
}

.mcp-row__identity {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.mcp-row__title {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
}

.mcp-row__name {
  color: var(--text-primary);
  font-size: var(--fs-ui);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mcp-row.is-off .mcp-row__name {
  color: var(--text-secondary);
}

.mcp-row__meta-line {
  margin: 0;
  overflow: hidden;
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-aux);
  white-space: nowrap;
  text-overflow: ellipsis;
  font-variant-numeric: tabular-nums;
}

.mcp-row__tail {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
}

.mcp-row__tools {
  display: inline-flex;
  align-items: baseline;
  gap: 3px;
  color: var(--text-primary);
  font-family: var(--mono);
  font-size: var(--fs-ui);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.mcp-row__tools small {
  color: var(--text-tertiary);
  font-family: var(--font);
  font-size: var(--fs-kicker);
  font-weight: 500;
}

@media (max-width: 760px) {
  .mcp-row {
    grid-template-columns: auto minmax(0, 1fr) auto;
  }
}

@media (max-width: 640px) {
  .mcp-row {
    padding: var(--gap-3);
  }
}
</style>
