<script setup lang="ts">
import { Label } from '@/shared/components/ui/label'
import { computed, ref } from 'vue'
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from '@lucide/vue'
import { Button } from '../button'
import { Input } from '../input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../select'
const props = withDefaults(defineProps<{
  currentPage?: number; pageSize?: number; total?: number; pageSizes?: number[]; layout?: string;
  disabled?: boolean; pagerCount?: number; background?: boolean; size?: string; small?: boolean
}>(), { currentPage: 1, pageSize: 20, total: 0, pageSizes: () => [10, 20, 50, 100], layout: 'total, sizes, prev, pager, next, jumper', pagerCount: 5 })
const emit = defineEmits<{ 'update:currentPage': [value: number]; 'update:pageSize': [value: number]; 'current-change': [value: number]; 'size-change': [value: number] }>()
const jump = ref<string | number>('')
const pages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))
const current = computed(() => Math.min(pages.value, Math.max(1, props.currentPage)))
const visible = computed(() => {
  const count = Math.max(3, props.pagerCount)
  const start = Math.max(1, Math.min(current.value - Math.floor(count / 2), pages.value - count + 1))
  return Array.from({ length: Math.min(count, pages.value) }, (_, index) => start + index)
})
function has(part: string) { return props.layout.split(',').map(value => value.trim()).includes(part) }
function page(next: number) { if (props.disabled || !Number.isFinite(next)) return; const value = Math.max(1, Math.min(pages.value, next)); emit('update:currentPage', value); emit('current-change', value) }
function size(raw: unknown) { const value = Number(raw); if (props.disabled || !Number.isFinite(value) || value <= 0) return; emit('update:pageSize', value); emit('size-change', value) }
</script>
<template>
  <nav class="pager" aria-label="分页">
    <span v-if="has('total')" class="pager__total">共 {{ total }} 条</span>
    <Select v-if="has('sizes')" :model-value="String(pageSize)" :disabled="disabled" @update:model-value="size">
      <SelectTrigger aria-label="每页条数" class="h-8 w-auto min-w-24"><SelectValue /></SelectTrigger>
      <SelectContent><SelectItem v-for="value in pageSizes" :key="value" :value="String(value)">{{ value }} 条 / 页</SelectItem></SelectContent>
    </Select>
    <div class="pager__pages">
      <Button access="read" v-if="has('prev')" type="button" variant="ghost" size="icon-sm" :disabled="disabled || current <= 1" aria-label="上一页" @click="page(current - 1)"><ChevronLeft /></Button>
      <template v-if="has('pager')"><Button access="read" v-if="visible[0] > 1" type="button" variant="ghost" size="icon-sm" :disabled="disabled" aria-label="第一页" @click="page(1)"><ChevronsLeft /></Button>
        <Button access="read" v-for="value in visible" :key="value" type="button" :variant="current === value ? 'secondary' : 'ghost'" size="sm" :class="current === value ? 'bg-active font-semibold text-ink' : 'text-ink-2'" :aria-current="current === value ? 'page' : undefined" :aria-label="`第 ${value} 页`" :disabled="disabled" @click="page(value)">{{ value }}</Button>
        <Button access="read" v-if="visible[visible.length - 1] < pages" type="button" variant="ghost" size="icon-sm" :disabled="disabled" aria-label="最后一页" @click="page(pages)"><ChevronsRight /></Button>
      </template>
      <Button access="read" v-if="has('next')" type="button" variant="ghost" size="icon-sm" :disabled="disabled || current >= pages" aria-label="下一页" @click="page(current + 1)"><ChevronRight /></Button>
    </div>
    <Label v-if="has('jumper')" class="pager__jump">跳至<Input v-model="jump" type="number" :min="1" :max="pages" :disabled="disabled" aria-label="跳转页码" @keydown.enter.prevent="page(Number(jump))" @change="page(Number(jump))" />页</Label>
  </nav>
</template>
