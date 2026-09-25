<script setup lang="ts">
import { Spinner } from '@/shared/components/ui/spinner'
/**
 * 异常条：正常时父级不渲染它，出错也只占一行——左侧琥珀色条 + 一句话 + 详情/重试。
 */
import { computed } from 'vue'
import { TriangleAlert } from '@lucide/vue'

import { Button } from '@/shared/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/shared/components/ui/popover'

export interface PulseIssue {
  key: string
  /** 一句话标题（≤10 字），如「行情更新失败」 */
  label: string
  /** 原始报错全文，进 popover */
  detail: string
}

const props = defineProps<{
  issues: PulseIssue[]
  busy?: boolean
}>()

const emit = defineEmits<{
  retry: []
}>()

const headline = computed(() => {
  const first = props.issues[0]
  if (!first) return ''
  const count = props.issues.length
  return count > 1 ? `${count} 项异常 · ${first.label}` : first.label
})
</script>

<template>
  <div v-if="issues.length" class="pulse-issues" role="status">
    <TriangleAlert class="pulse-issues__mark" aria-hidden="true" />
    <span class="pulse-issues__text">{{ headline }}</span>
    <span class="pulse-issues__actions">
      <Popover>
        <PopoverTrigger as-child>
          <Button access="read" variant="ghost" size="xs" class="pulse-issues__action">详情</Button>
        </PopoverTrigger>
        <PopoverContent align="end" class="w-[min(380px,calc(100vw-32px))]">
          <ul class="pulse-issues__list">
            <li v-for="issue in issues" :key="issue.key">
              <strong>{{ issue.label }}</strong>
              <span>{{ issue.detail }}</span>
            </li>
          </ul>
        </PopoverContent>
      </Popover>
      <Button access="read" variant="outline" size="xs" class="pulse-issues__action" :disabled="busy" @click="emit('retry')">
        <Spinner v-if="busy" class="size-3 animate-spin" aria-hidden="true" />
        重试
      </Button>
    </span>
  </div>
</template>

<style scoped>
.pulse-issues {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  min-width: 0;
  min-height: 40px;
  padding: 0 var(--gap-2) 0 var(--gap-3);
  border: 1px solid color-mix(in oklab, var(--warn) 30%, var(--border-subtle));
  border-radius: var(--radius-lg);
  background: color-mix(in oklab, var(--warn) 6%, var(--surface));
  color: var(--text-primary);
  font-size: var(--fs-ui);
}

.pulse-issues__mark {
  flex: 0 0 auto;
  width: 15px;
  height: 15px;
  color: var(--warn);
}

.pulse-issues__text {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pulse-issues__actions {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: var(--gap-1);
}

.pulse-issues__list {
  display: flex;
  flex-direction: column;
  gap: var(--gap-3);
  max-height: 50vh;
  margin: 0;
  padding: 0;
  overflow: auto;
  list-style: none;
}

.pulse-issues__list li {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.pulse-issues__list strong {
  font-size: var(--fs-ui);
  color: var(--text-primary);
}

.pulse-issues__list span {
  font-size: var(--fs-aux);
  color: var(--text-tertiary);
  overflow-wrap: anywhere;
}
</style>
