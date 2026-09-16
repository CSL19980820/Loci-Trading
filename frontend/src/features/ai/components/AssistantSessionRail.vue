<script setup lang="ts">
import { MoreFilled, Plus, Search, Select, Setting } from '@element-plus/icons-vue'
import { computed, ref, watch } from 'vue'

import EmptyState from '@/shared/components/ui/EmptyState.vue'
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
          :prefix-icon="Search"
          aria-label="搜索历史对话"
        />
        <div class="assistant-session-rail__top-actions">
          <el-tooltip :content="selecting ? '取消选择' : '多选'">
            <el-button :icon="Select" circle text :aria-label="selecting ? '取消多选' : '多选对话'" :aria-pressed="selecting" :disabled="disabled" @click="selecting = !selecting; selected = []" />
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
        <EmptyState
          v-if="!loading && !visibleSessions.length"
          :description="keyword ? '未找到对话' : railTab === 'archived' ? '没有归档对话' : '还没有对话'"
          :reason="keyword ? '换个关键词试试' : railTab === 'archived' ? '恢复后回到对话列表' : '新建对话开始提问'"
        />
        <div
          v-for="session in visibleSessions"
          :key="session.id"
          class="assistant-session-row"
          :class="{ 'is-active': session.id === activeId }"
        >
          <el-checkbox
            v-if="selecting"
            :aria-label="`选择对话 ${session.title || '新对话'}`"
            :model-value="selected.includes(session.id)"
            :disabled="disabled"
            @change="(value: string | number | boolean) => toggleSelect(session.id, Boolean(value))"
          />
          <el-button link class="assistant-session-row__main" :aria-current="session.id === activeId ? 'true' : undefined" :title="session.title || '新对话'" :disabled="disabled" @click="emit('select', session.id)">
            <span class="assistant-session-row__title">{{ session.title || '新对话' }}</span>
            <small class="assistant-session-row__meta" :title="session.model || session.status">{{ session.model || session.status }}</small>
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
              :aria-label="`${session.title || '新对话'}的操作`"
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
          <span class="assistant-session-rail__loci" aria-label="Loci"><span class="assistant-session-rail__glyph" aria-hidden="true">LC</span></span>
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
.assistant-session-rail { display: flex; flex: 0 1 280px; min-width: 220px; min-height: 0; flex-direction: column; border-right: 1px solid var(--rule); background: var(--surface-sunken); }
/* 与 Panel 的 JS 折叠断点一致；收起后必须清除展开态的最小宽度。 */
.assistant-session-rail.is-collapsed { flex: 0 0 48px; min-width: 0; width: 48px; }
.assistant-session-rail__collapsed { display: flex; flex: 1; flex-direction: column; align-items: center; justify-content: space-between; padding: var(--gap-2) 0; gap: var(--gap-2); }
.assistant-session-rail__collapsed-top { display: flex; flex-direction: column; align-items: center; gap: var(--gap-2); }
.assistant-session-rail__icon-btn { margin: 0 !important; width: var(--ctl-h) !important; height: var(--ctl-h) !important; padding: 0 !important; }
.assistant-session-rail__foot { display: flex; align-items: center; justify-content: space-between; gap: var(--gap-2); padding: var(--gap-2) var(--gap-3); border-top: 1px solid var(--rule); margin-top: auto; }
.assistant-session-rail__loci { display: inline-flex; align-items: center; justify-content: center; width: var(--ctl-h); height: var(--ctl-h); }
.assistant-session-rail__glyph { display: grid; place-items: center; width: var(--ctl-h); height: var(--ctl-h); border: 1px solid var(--rule); border-radius: var(--ai-r-chip); background: var(--surface); color: var(--seal-ink); font: 650 var(--ai-fs-meta) var(--mono); }
.assistant-session-rail__head, .assistant-session-rail__top { display: flex; align-items: center; gap: var(--gap-1); padding: var(--gap-2); }
.assistant-session-rail__top { border-bottom: 1px solid var(--rule); }
.assistant-session-rail__tabs, .assistant-session-rail__search { min-width: 0; flex: 1; }
.assistant-session-rail__top-actions { display: flex; flex: 0 0 auto; align-items: center; }
.assistant-session-rail__top-actions :deep(.el-button + .el-button) { margin-left: 0; }
.assistant-session-rail__batch { display: flex; flex-wrap: wrap; align-items: center; gap: var(--gap-1); padding: var(--gap-2); border-bottom: 1px solid var(--rule); font: var(--ai-fs-meta) var(--mono); color: var(--mist); background: var(--surface); }
.assistant-session-rail__list { display: flex; min-height: 0; flex: 1; flex-direction: column; overflow: auto; overscroll-behavior: contain; scrollbar-width: thin; gap: var(--gap-1); padding: var(--gap-2); }
.assistant-session-row { display: flex; align-items: center; gap: var(--gap-1); width: 100%; min-width: 0; box-sizing: border-box; padding: var(--gap-2); border-radius: var(--ai-r-card); border: 1px solid transparent; }
.assistant-session-row:hover, .assistant-session-row:focus-within { background: var(--surface-hover); }
.assistant-session-row.is-active { border-color: var(--seal-border); background: var(--seal-soft); }
.assistant-session-row__main { display: flex !important; min-width: 0; flex: 1; flex-direction: column; align-items: flex-start; justify-content: center; height: auto !important; padding: 0 !important; overflow: hidden; color: var(--ink); text-align: left; line-height: 1.5; }
.assistant-session-row__main :deep(> span) { display: flex; flex-direction: column; align-items: flex-start; gap: var(--gap-1); width: 100%; min-width: 0; }
.assistant-session-row__title, .assistant-session-row__meta { display: block; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: left; }
.assistant-session-row__title { font-size: var(--ai-fs-body); font-weight: 600; color: var(--ink); }
.assistant-session-row__meta { color: var(--mist); font: var(--ai-fs-meta) var(--mono); }
.assistant-session-row__more { flex: 0 0 auto; margin: 0 !important; color: var(--mist); }
.assistant-session-row__danger { color: var(--stamp); }
.assistant-session-rail :deep(button:focus-visible) { outline: 2px solid var(--seal); outline-offset: -2px; }
/* 折叠图标内的线代表真实面板分栏，不是装饰状态竖线。 */
.assistant-panel-toggle-icon { display: block; width: 1em; height: .9em; border: 1.5px solid currentColor; border-radius: var(--ai-r-chip); }
.assistant-panel-toggle-icon.is-left { box-shadow: inset 4px 0 0 currentColor; }
</style>
