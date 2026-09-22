<script setup lang="ts">
import { Sidebar, SidebarHeader, SidebarContent, SidebarMenu, SidebarMenuItem, SidebarMenuButton, SidebarFooter } from '@/shared/components/ui/sidebar'
import { useVisitorMode } from '@/shared/composables/useAccess'
const visitor = useVisitorMode()
import { Archive, ArchiveRestore, Ellipsis, PanelLeftClose, PanelLeftOpen, Plus, Search, Settings2, SquareCheck, Trash2 } from '@lucide/vue'
import { vBusy } from '@/shared/directives/busy'

import { computed, ref, watch } from 'vue'

import { Button } from '@/shared/components/ui/button'
import { Checkbox } from '@/shared/components/ui/checkbox'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/shared/components/ui/dropdown-menu'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { Input } from '@/shared/components/ui/input'
import PageTabs from '@/shared/components/ui/PageTabs.vue'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import type { AiSessionSummary } from '@/shared/types/ai_assistant'

/**
 * 会话列表（ChatGPT / Claude 侧栏一路）：顶部「新建对话」满宽按钮 + 搜索框 + 对话/归档药片切换，
 * 中间每条会话一行（标题 + 模型 / 时间的小字），hover 才露出 `⋯`；底部品牌盘 + 设置。
 * `collapsed` 时在宽屏工作台里收成 48px 图标条；`drawer` 模式（贴右 / 窄屏）由父级用
 * 抽屉方式摆放，收起即整块不渲染。
 */
type SessionContextCommand = 'archive' | 'restore' | 'delete'

const props = defineProps<{
  sessions: AiSessionSummary[]
  archivedSessions: AiSessionSummary[]
  activeId?: string
  loading?: boolean
  disabled?: boolean
  railTab: 'active' | 'archived'
  collapsed?: boolean
  /** 抽屉模式：父级贴右 / 窄屏时传 true，收起态不渲染图标条 */
  drawer?: boolean
}>()

const emit = defineEmits<{
  select: [id: string]
  create: []
  remove: [id: string]
  archive: [id: string]
  restore: [id: string]
  settings: []
  'update:railTab': [tab: 'active' | 'archived']
  batch: [payload: { action: 'archive' | 'unarchive' | 'delete'; ids: string[] }]
  'update:collapsed': [value: boolean]
}>()

const keyword = ref('')
const selecting = ref(false)
const selected = ref<string[]>([])

const source = computed(() => (props.railTab === 'archived' ? props.archivedSessions : props.sessions))
const visibleSessions = computed(() => {
  const needle = keyword.value.trim().toLowerCase()
  return needle ? source.value.filter((session) => session.title.toLowerCase().includes(needle)) : source.value
})

const tabItems = computed(() => [
  { name: 'active', label: '对话', badge: props.sessions.length || undefined },
  { name: 'archived', label: '归档', badge: props.archivedSessions.length || undefined },
])

const railTabModel = computed({
  get: () => props.railTab,
  set: (next: string) => emit('update:railTab', next === 'archived' ? 'archived' : 'active'),
})

watch(() => props.railTab, () => {
  selecting.value = false
  selected.value = []
})

function toggleSelect(id: string, checked: boolean): void {
  selected.value = checked ? [...new Set([...selected.value, id])] : selected.value.filter((item) => item !== id)
}

function runBatch(action: 'archive' | 'unarchive' | 'delete'): void {
  if (!selected.value.length) return
  emit('batch', { action, ids: [...selected.value] })
  selected.value = []
  selecting.value = false
}

function onContextCommand(sessionId: string, command: SessionContextCommand | string): void {
  if (visitor.value) return
  if (props.disabled) return
  if (command === 'archive') emit('archive', sessionId)
  else if (command === 'restore') emit('restore', sessionId)
  else if (command === 'delete') emit('remove', sessionId)
}

function metaOf(session: AiSessionSummary): string {
  const when = (session.updated_at || '').replace('T', ' ').slice(5, 16)
  return [session.model, when].filter(Boolean).join(' · ') || session.status
}
</script>

<template>
  <Sidebar collapsible="none" role="complementary"
    class="assistant-session-rail"
    :class="{ 'is-collapsed': collapsed, 'is-drawer': drawer }"
    aria-label="历史对话"
    data-testid="assistant-session-rail"
  >
    <template v-if="collapsed">
      <div v-if="!drawer" class="assistant-session-rail__strip">
        <Tooltip>
          <TooltipTrigger as-child>
            <Button
              variant="ghost"
              size="icon-sm"
              access="read" aria-label="展开历史对话"
              data-testid="session-rail-expand"
              @click="emit('update:collapsed', false)"
            >
              <PanelLeftOpen />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="right">展开历史</TooltipContent>
        </Tooltip>
        <Tooltip v-if="railTab === 'active'">
          <TooltipTrigger as-child>
            <Button variant="ghost" size="icon-sm" aria-label="新建对话" :disabled="disabled" @click="emit('create')">
              <Plus />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="right">新建对话</TooltipContent>
        </Tooltip>
        <span class="assistant-session-rail__spacer" />
        <Tooltip>
          <TooltipTrigger as-child>
            <Button variant="ghost" size="icon-sm" aria-label="助手设置" data-testid="assistant-icon-settings" @click="emit('settings')">
              <Settings2 />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="right">助手设置</TooltipContent>
        </Tooltip>
      </div>
    </template>

    <template v-else>
      <SidebarHeader class="assistant-session-rail__top flex-row">
        <Button
          v-if="railTab === 'active'"
          variant="outline"
          class="assistant-session-rail__new"
          :disabled="disabled"
          @click="emit('create')"
        >
          <Plus />
          新建对话
        </Button>
        <Tooltip v-if="!drawer">
          <TooltipTrigger as-child>
            <Button
              variant="ghost"
              size="icon"
              access="read" aria-label="收起历史对话"
              data-testid="session-rail-collapse"
              @click="emit('update:collapsed', true)"
            >
              <PanelLeftClose />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">收起历史</TooltipContent>
        </Tooltip>
      </SidebarHeader>
      <div class="assistant-session-rail__search">
        <Search class="assistant-session-rail__search-icon" aria-hidden="true" />
        <Input
          v-model="keyword"
          size="sm"
          class="assistant-session-rail__search-input"
          placeholder="搜索对话"
          aria-label="搜索历史对话"
        />
      </div>
      <div class="assistant-session-rail__tabs">
        <PageTabs v-model="railTabModel" :items="tabItems" variant="pill" dense :sticky="false" aria-label="对话分组" />
        <Tooltip>
          <TooltipTrigger as-child>
            <Button
              variant="ghost"
              size="icon-sm"
              :class="{ 'is-on': selecting }"
              :aria-label="selecting ? '取消多选' : '多选对话'"
              :aria-pressed="selecting"
              :disabled="disabled"
              @click="selecting = !selecting; selected = []"
            >
              <SquareCheck />
            </Button>
          </TooltipTrigger>
          <TooltipContent>{{ selecting ? '取消选择' : '多选' }}</TooltipContent>
        </Tooltip>
      </div>
      <div v-if="selecting && !visitor" class="assistant-session-rail__batch" data-testid="session-rail-batch">
        <span>已选 {{ selected.length }}</span>
        <Button v-if="railTab === 'active'" size="xs" variant="outline" :disabled="!selected.length || disabled" @click="runBatch('archive')">归档</Button>
        <Button v-else size="xs" variant="outline" :disabled="!selected.length || disabled" @click="runBatch('unarchive')">恢复</Button>
        <Button size="xs" variant="soft-destructive" :disabled="!selected.length || disabled" @click="runBatch('delete')">删除</Button>
      </div>
      <SidebarContent v-busy="loading" class="assistant-session-rail__list">
        <EmptyState
          v-if="!loading && !visibleSessions.length"
          compact
          :description="keyword ? '未找到对话' : railTab === 'archived' ? '没有归档对话' : '还没有对话'"
          :reason="keyword ? '换个关键词试试' : railTab === 'archived' ? '恢复后回到对话列表' : '新建对话开始提问'"
        />
        <SidebarMenu><SidebarMenuItem
          v-for="session in visibleSessions"
          :key="session.id"
          class="assistant-session-row"
          :class="{ 'is-active': session.id === activeId }"
        >
          <Checkbox
            v-if="selecting"
            :aria-label="`选择对话 ${session.title || '新对话'}`"
            :model-value="selected.includes(session.id)"
            :disabled="disabled"
            @update:model-value="(value) => toggleSelect(session.id, value === true)"
          />
          <SidebarMenuButton :is-active="session.id === activeId"
            type="button"
            class="assistant-session-row__main"
            :aria-current="session.id === activeId ? 'true' : undefined"
            :title="session.title || '新对话'"
            :disabled="disabled"
            @click="emit('select', session.id)"
          >
            <span class="assistant-session-row__title">{{ session.title || '新对话' }}</span>
            <small class="assistant-session-row__meta">{{ metaOf(session) }}</small>
          </SidebarMenuButton>
          <DropdownMenu v-if="!selecting && !visitor">
            <DropdownMenuTrigger as-child>
              <Button
                variant="ghost"
                size="icon-xs"
                class="assistant-session-row__more"
                :aria-label="`${session.title || '新对话'}的操作`"
                :disabled="disabled"
                @click.stop
              >
                <Ellipsis />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem v-if="railTab === 'active'" @select="onContextCommand(session.id, 'archive')"><Archive />归档</DropdownMenuItem>
              <DropdownMenuItem v-else @select="onContextCommand(session.id, 'restore')"><ArchiveRestore />恢复</DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" @select="onContextCommand(session.id, 'delete')"><Trash2 />删除</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </SidebarMenuItem></SidebarMenu>
      </SidebarContent>
      <SidebarFooter class="assistant-session-rail__foot flex-row">
        <span class="assistant-session-rail__brand" aria-label="Loci">
          <span class="assistant-session-rail__glyph" aria-hidden="true">LC</span>
          <span class="assistant-session-rail__brand-text">Loci 助手</span>
        </span>
        <Tooltip>
          <TooltipTrigger as-child>
            <Button variant="ghost" size="icon-sm" aria-label="助手设置" data-testid="assistant-icon-settings" @click="emit('settings')">
              <Settings2 />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="top">助手设置</TooltipContent>
        </Tooltip>
      </SidebarFooter>
    </template>
  </Sidebar>
</template>

<style scoped>
.assistant-session-rail {
  display: flex;
  flex: 0 1 280px;
  flex-direction: column;
  min-width: 240px;
  min-height: 0;
  border-right: 1px solid var(--border-subtle);
  background: var(--surface-canvas);
}

.assistant-session-rail.is-collapsed {
  flex: 0 0 48px;
  width: 48px;
  min-width: 0;
}

.assistant-session-rail.is-drawer {
  min-width: 0;
  background: var(--surface);
}

.assistant-session-rail__strip {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  gap: var(--gap-1);
  padding: var(--gap-2) 0;
}

.assistant-session-rail__spacer {
  flex: 1;
}

.assistant-session-rail__top {
  display: flex;
  align-items: center;
  gap: var(--gap-1);
  padding: var(--gap-3) var(--gap-3) var(--gap-2);
}

.assistant-session-rail__new {
  flex: 1 1 auto;
  justify-content: flex-start;
  min-width: 0;
  font-weight: 500;
}

.assistant-session-rail__search {
  position: relative;
  padding: 0 var(--gap-3);
}

.assistant-session-rail__search-icon {
  position: absolute;
  top: 50%;
  left: calc(var(--gap-3) + 9px);
  width: 14px;
  height: 14px;
  color: var(--text-tertiary);
  transform: translateY(-50%);
  pointer-events: none;
}

.assistant-session-rail__search-input {
  padding-left: 28px;
  background: var(--surface);
}

.assistant-session-rail__tabs {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-2);
  padding: var(--gap-2) var(--gap-3);
}

.assistant-session-rail__tabs :deep(.is-on) {
  background: var(--surface-active);
  color: var(--text-primary);
}

.assistant-session-rail__batch {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-1);
  margin: 0 var(--gap-3) var(--gap-2);
  padding: var(--gap-1) var(--gap-2);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
}

.assistant-session-rail__batch > span {
  margin-right: auto;
}

.assistant-session-rail__list {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 1px;
  min-height: 0;
  padding: 0 var(--gap-2) var(--gap-2);
  overflow: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
}

.assistant-session-row {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  width: 100%;
  min-width: 0;
  padding: 0 var(--gap-1) 0 var(--gap-2);
  border-radius: var(--radius);
  transition: background var(--dur-fast) var(--ease);
}

.assistant-session-row:hover,
.assistant-session-row:focus-within {
  background: var(--surface-hover);
}

.assistant-session-row.is-active {
  background: var(--surface-active);
}

.assistant-session-row__main {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 2px;
  min-width: 0;
  min-height: 44px;
  padding: 6px 0;
  border: 0;
  background: transparent;
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
}

.assistant-session-row__main:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.assistant-session-row__title,
.assistant-session-row__meta {
  display: block;
  max-width: 100%;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.assistant-session-row__title {
  color: var(--text-primary);
  font-size: var(--fs-ui);
  font-weight: 500;
}

.assistant-session-row.is-active .assistant-session-row__title {
  font-weight: 600;
}

.assistant-session-row__meta {
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  font-variant-numeric: tabular-nums;
}

.assistant-session-row__more {
  flex: 0 0 auto;
  color: var(--text-tertiary);
  opacity: 0;
  transition: opacity var(--dur-fast) var(--ease);
}

.assistant-session-row:hover .assistant-session-row__more,
.assistant-session-row:focus-within .assistant-session-row__more,
.assistant-session-row.is-active .assistant-session-row__more {
  opacity: 1;
}

@media (hover: none) {
  .assistant-session-row__more {
    opacity: 1;
  }
}

.assistant-session-rail__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-2);
  margin-top: auto;
  padding: var(--gap-2) var(--gap-3);
  border-top: 1px solid var(--border-subtle);
}

.assistant-session-rail__brand {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-2);
  min-width: 0;
}

.assistant-session-rail__glyph {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: linear-gradient(160deg, color-mix(in oklab, var(--seal) 90%, white), var(--seal-hover));
  color: var(--on-primary);
  font-family: var(--mono);
  font-size: 9px;
  font-weight: 700;
}

.assistant-session-rail__brand-text {
  color: var(--text-secondary);
  font-size: var(--fs-aux);
  font-weight: 500;
}

.assistant-session-rail :deep(button:focus-visible) {
  outline: 2px solid var(--focus-ring);
  outline-offset: -2px;
}
</style>
