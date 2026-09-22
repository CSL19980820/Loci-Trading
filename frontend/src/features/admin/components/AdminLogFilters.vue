<script setup lang="ts">
/**
 * 日志类列表的筛选行：关键词 + 两个下拉（动作 / 结果）+ 查询 / 重置。
 * 审计与登录共用；`v-model` 直接绑 `LogFilters`（keyword / action / outcome 三键）。
 * Select 不接受空串当「全部」，内部用哨兵值来回映射。
 */
import { RefreshCw, Search } from '@lucide/vue'
import { computed } from 'vue'

import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/components/ui/select'
import type { DictOption } from '../lib/adminDict'
import type { LogFilters } from './logTableParts'

const ALL = '__all__'

const props = defineProps<{
  keywordPlaceholder: string
  actionLabel: string
  actionOptions: readonly DictOption[]
  outcomeLabel: string
  outcomeOptions: readonly DictOption[]
}>()

const filters = defineModel<LogFilters>({ required: true })

const emit = defineEmits<{ search: []; reset: [] }>()

const keyword = computed({
  get: () => String(filters.value.keyword ?? ''),
  set: (next: string | number) => {
    filters.value = { ...filters.value, keyword: String(next) }
  },
})

function pick(key: 'action' | 'outcome') {
  return computed({
    get: () => String(filters.value[key] ?? '') || ALL,
    set: (next: string) => {
      filters.value = { ...filters.value, [key]: next === ALL ? '' : next }
    },
  })
}

const actionPick = pick('action')
const outcomePick = pick('outcome')

const actionAll = computed(() => `全部${props.actionLabel}`)
const outcomeAll = computed(() => `全部${props.outcomeLabel}`)
</script>

<template>
  <div class="log-filters" role="search">
    <div class="log-filters__search">
      <Search class="log-filters__icon" aria-hidden="true" />
      <Input
        v-model="keyword"
        size="sm"
        class="log-filters__input"
        :placeholder="keywordPlaceholder"
        aria-label="关键词"
        @keyup.enter="emit('search')"
      />
    </div>
    <Select v-model="actionPick">
      <SelectTrigger size="sm" class="log-filters__select" :aria-label="actionLabel">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem :value="ALL">{{ actionAll }}</SelectItem>
        <SelectItem v-for="opt in actionOptions" :key="String(opt.value)" :value="String(opt.value)">{{ opt.label }}</SelectItem>
      </SelectContent>
    </Select>
    <Select v-model="outcomePick">
      <SelectTrigger size="sm" class="log-filters__select" :aria-label="outcomeLabel">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem :value="ALL">{{ outcomeAll }}</SelectItem>
        <SelectItem v-for="opt in outcomeOptions" :key="String(opt.value)" :value="String(opt.value)">{{ opt.label }}</SelectItem>
      </SelectContent>
    </Select>
    <div class="log-filters__actions">
      <Button size="sm" variant="outline" @click="emit('search')"><Search />查询</Button>
      <Button size="sm" variant="ghost" @click="emit('reset')"><RefreshCw />重置</Button>
    </div>
  </div>
</template>

<style scoped>
.log-filters {
  display: flex;
  flex-shrink: 0;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2);
}

.log-filters__search {
  position: relative;
  flex: 1 1 240px;
  min-width: 0;
  max-width: 360px;
}

.log-filters__icon {
  position: absolute;
  top: 50%;
  left: 9px;
  width: 14px;
  height: 14px;
  color: var(--text-tertiary);
  transform: translateY(-50%);
  pointer-events: none;
}

.log-filters__input {
  padding-left: 28px;
}

.log-filters__select {
  min-width: 120px;
}

.log-filters__actions {
  display: flex;
  align-items: center;
  gap: var(--gap-1);
  margin-left: auto;
}

@media (max-width: 640px) {
  .log-filters { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .log-filters__search { grid-column: 1; grid-row: 1; max-width: none; }
  .log-filters__actions { grid-column: 2; grid-row: 1; margin-left: auto; }
  .log-filters__select { min-width: 0; width: 100%; }
  .log-filters__actions > :deep(button) { min-height: 32px; padding-inline: 8px; }
}
</style>
