<script setup lang="ts">
/**
 * 同批切票：一枚步进器（上一只 · 位置 · 下一只）+ 「本批」列表开关 + 来源 chip。
 * 「返回本批」并进了页头的返回按钮（goBack 本来就会回来源页），这里不再重复放一颗。
 */
import { computed } from 'vue'
import { ChevronLeft, ChevronRight, List } from '@lucide/vue'

import { Button } from '@/shared/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import { parseBatchSource } from '@/shared/lib/batchBrowse'

const props = defineProps<{
  positionLabel: string
  source: string
  canPrev: boolean
  canNext: boolean
  dockOpen: boolean
}>()

const emit = defineEmits<{
  prev: []
  next: []
  'return-batch': []
  'toggle-dock': []
}>()

const parsed = computed(() => parseBatchSource(props.source))
const dockLabel = computed(() => (props.dockOpen ? '收起本批' : '本批'))
</script>

<template>
  <div class="batch-rail" aria-label="同批切票">
    <Tooltip v-if="parsed.date || parsed.title" :delay-duration="200">
      <TooltipTrigger as-child>
        <Button access="read" variant="ghost" type="button" class="batch-rail__chip" @click="emit('return-batch')">
          <span class="batch-rail__chip-title">{{ parsed.title || '本批' }}</span>
          <span v-if="parsed.date" class="batch-rail__chip-date">{{ parsed.date }}</span>
        </Button>
      </TooltipTrigger>
      <TooltipContent>{{ parsed.full }} · 点击返回来源页</TooltipContent>
    </Tooltip>

    <div class="batch-rail__stepper" role="group" :aria-label="`同批 ${positionLabel}`">
      <Button access="read"
        variant="ghost"
        size="icon-sm"
        class="batch-rail__step"
        :disabled="!canPrev"
        aria-label="上一只"
        aria-keyshortcuts="ArrowLeft"
        @click="emit('prev')"
      >
        <ChevronLeft aria-hidden="true" />
      </Button>
      <span class="batch-rail__pos">{{ positionLabel }}</span>
      <Button access="read"
        variant="ghost"
        size="icon-sm"
        class="batch-rail__step"
        :disabled="!canNext"
        aria-label="下一只"
        aria-keyshortcuts="ArrowRight"
        @click="emit('next')"
      >
        <ChevronRight aria-hidden="true" />
      </Button>
    </div>

    <Button access="read" variant="outline" size="sm" :aria-expanded="dockOpen" @click="emit('toggle-dock')">
      <List aria-hidden="true" />
      {{ dockLabel }}
    </Button>
  </div>
</template>

<style scoped>
.batch-rail {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2);
  min-width: 0;
}

.batch-rail__chip {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  max-width: 16rem;
  height: var(--ctl-h-sm);
  padding: 0 10px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-pill);
  background: var(--surface-sunken);
  color: var(--text-secondary);
  font: 500 var(--fs-aux) / 1 var(--font);
  cursor: pointer;
  transition:
    border-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

.batch-rail__chip:hover {
  border-color: var(--border-default);
  color: var(--text-primary);
}

.batch-rail__chip:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 2px;
}

.batch-rail__chip-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.batch-rail__chip-date {
  flex-shrink: 0;
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  font-variant-numeric: tabular-nums;
}

.batch-rail__stepper {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  height: var(--ctl-h-sm);
  padding: 0 2px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--shadow-xs);
}

.batch-rail__step {
  width: 24px;
  height: 24px;
}

.batch-rail__pos {
  min-width: 3.4rem;
  text-align: center;
  color: var(--text-primary);
  font-family: var(--mono);
  font-size: var(--fs-aux);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

@media (max-width: 640px) {
  .batch-rail {
    display: flex;
    width:100%; flex-wrap:nowrap; gap:5px;
  }

  .batch-rail__chip {
    flex:1 1 auto; min-width:0; max-width:none;
  }

  .batch-rail__stepper,
  .batch-rail__chip,
  .batch-rail > :deep(button) {
    height:32px; font-size:11px;
  }
}
@media(max-width:640px) { .batch-rail__stepper { flex:none; } .batch-rail__chip-date { display:none; } .batch-rail__pos { min-width:36px; font-size:11px; } .batch-rail > :deep(button) { flex:none; padding-inline:8px; } }
</style>
