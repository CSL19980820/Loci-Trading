<script setup lang="ts">
import { Delete, Plus } from '@element-plus/icons-vue'
import { computed, ref } from 'vue'

import type { AiSessionSummary } from '@/shared/types/ai_assistant'

const props = defineProps<{ sessions: AiSessionSummary[]; activeId?: string; loading?: boolean; disabled?: boolean }>()
const emit = defineEmits<{ select: [id: string]; create: []; remove: [id: string] }>()
const keyword = ref('')
const visibleSessions = computed(() => {
  const needle = keyword.value.trim().toLowerCase()
  return needle ? props.sessions.filter((session) => session.title.toLowerCase().includes(needle)) : props.sessions
})
</script>

<template>
  <aside class="assistant-session-rail" aria-label="历史对话">
    <div class="assistant-session-rail__top">
      <el-input v-model="keyword" size="small" clearable placeholder="搜索对话" aria-label="搜索历史对话" />
      <el-tooltip content="新建对话">
        <el-button :icon="Plus" circle text aria-label="新建对话" :disabled="disabled" @click="emit('create')" />
      </el-tooltip>
    </div>
    <div v-loading="loading" class="assistant-session-rail__list">
      <el-empty v-if="!loading && !visibleSessions.length" :image-size="48" description="还没有对话" />
      <div v-for="session in visibleSessions" :key="session.id" class="assistant-session-row" :class="{ 'is-active': session.id === activeId }">
        <el-button link class="assistant-session-row__main" :disabled="disabled" @click="emit('select', session.id)">
          <span>{{ session.title || '新对话' }}</span>
          <small>{{ session.model || session.status }}</small>
        </el-button>
        <el-tooltip content="删除对话">
          <el-button :icon="Delete" circle text size="small" aria-label="删除对话" :disabled="disabled" @click="emit('remove', session.id)" />
        </el-tooltip>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.assistant-session-rail { display: flex; flex: 0 0 176px; min-width: 0; flex-direction: column; border-right: 1px solid var(--rule); background: var(--panel-2); }
.assistant-session-rail__top { display: flex; gap: .3rem; padding: .55rem; border-bottom: 1px solid var(--rule); }
.assistant-session-rail__list { min-height: 0; flex: 1; overflow: auto; }
.assistant-session-row { display: flex; align-items: center; gap: .1rem; padding: .18rem .35rem .18rem .55rem; border-bottom: 1px solid color-mix(in srgb, var(--rule) 75%, transparent); }
.assistant-session-row.is-active { border-left: 2px solid var(--el-color-primary); background: var(--seal-soft); padding-left: calc(.55rem - 2px); }
.assistant-session-row__main { display: grid; min-width: 0; flex: 1; justify-items: start; overflow: hidden; color: var(--ink); text-align: left; }
.assistant-session-row__main span, .assistant-session-row__main small { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.assistant-session-row__main small { color: var(--mist); font-size: .7rem; }
</style>
