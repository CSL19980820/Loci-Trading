<script setup lang="ts">
import { MoreFilled, Plus, Select, Setting } from '@element-plus/icons-vue'
import { computed, ref, watch } from 'vue'

import type { AiSessionSummary } from '@/shared/types/ai_assistant'

type SessionContextCommand = 'archive' | 'restore' | 'delete'

const props = defineProps<{
  sessions: AiSessionSummary[]
  archivedSessions: AiSessionSummary[]
  activeId?: string
  loading?: boolean
  disabled?: boolean
  railTab: 'active' | 'archived'
  collapsed?: boolean
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
  if (props.disabled) return
  if (command === 'archive') emit('archive', sessionId)
  else if (command === 'restore') emit('restore', sessionId)
  else if (command === 'delete') emit('remove', sessionId)
}
</script>

<template>
  <aside
    class="assistant-session-rail"
    :class="{ 'is-collapsed': collapsed }"
    aria-label="历史对话"
    data-testid="assistant-session-rail"
  >
    <template v-if="collapsed">
      <div class="assistant-session-rail__collapsed">
        <div class="assistant-session-rail__collapsed-top">
          <el-tooltip content="展开历史" placement="right">
            <el-button
              circle
              text
              class="assistant-session-rail__icon-btn"
              aria-label="展开历史对话"
              data-testid="session-rail-expand"
              @click="emit('update:collapsed', false)"
            >
              <span class="assistant-panel-toggle-icon is-left" aria-hidden="true" />
            </el-button>
          </el-tooltip>
          <el-tooltip v-if="railTab === 'active'" content="新建对话" placement="right">
            <el-button
              :icon="Plus"
              circle
              text
              class="assistant-session-rail__icon-btn"
              aria-label="新建对话"
              :disabled="disabled"
              @click="emit('create')"
            />
          </el-tooltip>
        </div>
        <el-tooltip content="助手设置" placement="right">
          <el-button
            class="assistant-session-rail__loci assistant-session-rail__icon-btn"
            circle
            text
            aria-label="助手设置"
            data-testid="assistant-icon-settings"
            @click="emit('settings')"
          >
            <span class="assistant-session-rail__glyph" aria-hidden="true">LC</span>
          </el-button>
        </el-tooltip>
      </div>
    </template>

    <template v-else>
      <div class="assistant-session-rail__head">
        <div class="assistant-session-rail__tabs">
          <el-segmented
            :model-value="railTab"
            :options="[{ label: '对话', value: 'active' }, { label: '归档', value: 'archived' }]"
            size="small"
            @change="(value: string | number | boolean) => emit('update:railTab', value === 'archived' ? 'archived' : 'active')"
          />
        </div>
        <el-tooltip content="收起历史" placement="bottom">
          <el-button
            circle
            text
            class="assistant-session-rail__icon-btn"
            aria-label="收起历史对话"
            data-testid="session-rail-collapse"
            @click="emit('update:collapsed', true)"
          >
            <span class="assistant-panel-toggle-icon is-left is-open" aria-hidden="true" />
          </el-button>
        </el-tooltip>
      </div>
      <div class="assistant-session-rail__top">
        <el-input
          v-model="keyword"
          class="assistant-session-rail__search"
          size="small"
          clearable
          placeholder="搜索对话"
          aria-label="搜索历史对话"
        />
        <div class="assistant-session-rail__top-actions">
          <el-tooltip :content="selecting ? '取消选择' : '多选'">
            <el-button :icon="Select" circle text aria-label="多选对话" :disabled="disabled" @click="selecting = !selecting; selected = []" />
          </el-tooltip>
          <el-tooltip v-if="railTab === 'active'" content="新建对话">
            <el-button :icon="Plus" circle text aria-label="新建对话" :disabled="disabled" @click="emit('create')" />
          </el-tooltip>
        </div>
      </div>
      <div v-if="selecting" class="assistant-session-rail__batch" data-testid="session-rail-batch">
        <span>已选 {{ selected.length }}</span>
        <el-button v-if="railTab === 'active'" size="small" :disabled="!selected.length || disabled" @click="runBatch('archive')">归档</el-button>
        <el-button v-else size="small" :disabled="!selected.length || disabled" @click="runBatch('unarchive')">恢复</el-button>
        <el-button size="small" type="danger" plain :disabled="!selected.length || disabled" @click="runBatch('delete')">删除</el-button>
      </div>
      <div v-loading="loading" class="assistant-session-rail__list">
        <el-empty
          v-if="!loading && !visibleSessions.length"
          :image-size="48"
          :description="railTab === 'archived' ? '没有归档对话' : '还没有对话'"
        />
        <div
          v-for="session in visibleSessions"
          :key="session.id"
          class="assistant-session-row"
          :class="{ 'is-active': session.id === activeId }"
        >
          <el-checkbox
            v-if="selecting"
            :model-value="selected.includes(session.id)"
            :disabled="disabled"
            @change="(value: string | number | boolean) => toggleSelect(session.id, Boolean(value))"
          />
          <el-button link class="assistant-session-row__main" :disabled="disabled" @click="emit('select', session.id)">
            <span class="assistant-session-row__title">{{ session.title || '新对话' }}</span>
            <small class="assistant-session-row__meta">{{ session.model || session.status }}</small>
          </el-button>
          <el-dropdown
            v-if="!selecting"
            trigger="click"
            placement="bottom-end"
            :disabled="disabled"
            teleported
            @command="(command: string | number) => onContextCommand(session.id, String(command))"
          >
            <el-button
              class="assistant-session-row__more"
              :icon="MoreFilled"
              circle
              text
              size="small"
              aria-label="对话操作"
              :disabled="disabled"
              @click.stop
            />
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-if="railTab === 'active'" command="archive">归档</el-dropdown-item>
                <el-dropdown-item v-else command="restore">恢复</el-dropdown-item>
                <el-dropdown-item divided command="delete" class="assistant-session-row__danger">删除</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
      <div class="assistant-session-rail__foot">
        <el-tooltip content="Loci" placement="top">
          <el-button class="assistant-session-rail__loci" circle text aria-label="Loci" tabindex="-1">
            <span class="assistant-session-rail__glyph" aria-hidden="true">LC</span>
          </el-button>
        </el-tooltip>
        <el-tooltip content="助手设置" placement="top">
          <el-button
            :icon="Setting"
            circle
            text
            aria-label="助手设置"
            data-testid="assistant-icon-settings"
            @click="emit('settings')"
          />
        </el-tooltip>
      </div>
    </template>
  </aside>
</template>

<style scoped>
.assistant-session-rail {
  display: flex;
  /*
   * 同 AssistantTaskSidebar：shrink 因子 0 会让 min-width 失效、窄屏挤没正文区。
   * 900px 以下由 AssistantPanel 的断点折成 48px rail，这里只兜中间地带。
   */
  flex: 0 1 280px;
  min-width: 220px;
  flex-direction: column;
  border-right: 1px solid var(--rule);
  background: color-mix(in srgb, var(--panel-2) 92%, var(--ink) 2%);
  transition: flex-basis .18s ease, width .18s ease;
}
.assistant-session-rail.is-collapsed {
  flex: 0 0 48px;
  /* 展开态的 min-width 会把 48px 的 rail 撑回 220px，折叠时必须清掉 */
  min-width: 0;
  width: 48px;
  align-items: stretch;
  justify-content: stretch;
}
.assistant-session-rail__collapsed {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  justify-content: space-between;
  padding: .45rem 0 .55rem;
  gap: .35rem;
}
.assistant-session-rail__collapsed-top {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: .25rem;
}
.assistant-session-rail__icon-btn {
  margin: 0 !important;
  width: 2rem !important;
  height: 2rem !important;
  padding: 0 !important;
  display: inline-flex !important;
  align-items: center;
  justify-content: center;
}
.assistant-session-rail.is-collapsed :deep(.el-tooltip__trigger) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto;
}
.assistant-session-rail__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .35rem;
  padding: .45rem .55rem .55rem;
  border-top: 1px solid var(--rule);
  margin-top: auto;
}
.assistant-session-rail__loci {
  width: 2.1rem;
  height: 2.1rem;
}
.assistant-session-rail__glyph {
  display: grid;
  place-items: center;
  width: 1.7rem;
  height: 1.7rem;
  border-radius: var(--ai-r-card);
  background: var(--ai-disc-face);
  color: var(--ai-disc-ribbon);
  font-size: var(--ai-fs-meta);
  font-weight: 700;
  letter-spacing: .04em;
}
.assistant-session-rail__head {
  display: flex;
  align-items: center;
  gap: .25rem;
  padding: .55rem .45rem 0 .65rem;
}
.assistant-session-rail__tabs {
  min-width: 0;
  flex: 1;
}
.assistant-session-rail__top {
  display: flex;
  align-items: center;
  gap: .25rem;
  padding: .45rem .55rem;
  border-bottom: 1px solid var(--rule);
}
.assistant-session-rail__search {
  min-width: 0;
  flex: 1 1 auto;
}
.assistant-session-rail__top-actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 0;
}
.assistant-session-rail__top-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}
.assistant-session-rail__batch {
  display: flex;
  align-items: center;
  gap: .35rem;
  padding: .4rem .65rem;
  border-bottom: 1px solid var(--rule);
  font-size: var(--ai-fs-aux);
  color: var(--mist);
  background: color-mix(in srgb, var(--panel) 70%, transparent);
}
.assistant-session-rail__list {
  min-height: 0;
  flex: 1;
  overflow: auto;
  scrollbar-width: thin;
  padding: .4rem;
  display: flex;
  flex-direction: column;
  gap: .28rem;
}
/* 细滚动条而不是整个抹掉：长列表里用户需要位置感知 */
.assistant-session-rail__list::-webkit-scrollbar {
  width: 8px;
}
.assistant-session-rail__list::-webkit-scrollbar-track {
  background: transparent;
}
.assistant-session-rail__list::-webkit-scrollbar-thumb {
  border: 2px solid transparent;
  border-radius: var(--ai-r-pill);
  background: color-mix(in srgb, var(--ink) 18%, transparent);
  background-clip: padding-box;
}
.assistant-session-row {
  display: flex;
  align-items: center;
  gap: .2rem;
  width: 100%;
  padding: .4rem .45rem .4rem .55rem;
  border-radius: var(--ai-r-card);
  border: 1px solid transparent;
}
.assistant-session-row.is-active {
  border-color: color-mix(in srgb, var(--seal) 35%, var(--rule));
  background: var(--seal-soft);
}
.assistant-session-row__main {
  display: flex !important;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: .18rem;
  height: auto !important;
  padding: .15rem 0 !important;
  overflow: hidden;
  color: var(--ink);
  text-align: left;
  line-height: 1.25;
}
.assistant-session-row__main :deep(.el-button__content),
.assistant-session-row__main :deep(> span) {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: .08rem;
  width: 100%;
  min-width: 0;
}
.assistant-session-row__title,
.assistant-session-row__meta {
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: left;
}
.assistant-session-row__title {
  font-size: var(--ai-fs-body);
  font-weight: 600;
  color: var(--ink);
}
.assistant-session-row__meta {
  color: var(--mist);
  font-size: var(--ai-fs-meta);
  font-weight: 400;
}
.assistant-session-row__more {
  flex: 0 0 auto;
  margin: 0 !important;
  opacity: .35;
}
.assistant-session-row:hover .assistant-session-row__more,
.assistant-session-row.is-active .assistant-session-row__more {
  opacity: .9;
}
.assistant-session-row__danger { color: var(--el-color-danger); }

.assistant-panel-toggle-icon {
  display: block;
  width: .95rem;
  height: .85rem;
  border: 1.5px solid currentColor;
  border-radius: var(--ai-r-chip);
  opacity: .85;
}
.assistant-panel-toggle-icon.is-left {
  box-shadow: inset 4px 0 0 currentColor;
}
.assistant-panel-toggle-icon.is-left.is-open {
  box-shadow: inset 5px 0 0 currentColor;
}

@media (prefers-reduced-motion: reduce) {
  .assistant-session-rail { transition: none; }
}
</style>
