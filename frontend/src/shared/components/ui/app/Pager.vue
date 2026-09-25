<script setup lang="ts">
import { Label } from '@/shared/components/ui/label'
import { computed, ref } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from '@lucide/vue'
import { Pagination, PaginationContent, PaginationItem, PaginationEllipsis, PaginationFirst, PaginationLast, PaginationNext, PaginationPrevious } from '../pagination'
import { Input } from '../input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../select'
const props = withDefaults(defineProps<{
  currentPage?: number; pageSize?: number; total?: number; pageSizes?: number[]; layout?: string;
  disabled?: boolean; pagerCount?: number; background?: boolean; size?: string; small?: boolean
}>(), { currentPage: 1, pageSize: 20, total: 0, pageSizes: () => [10, 20, 50, 100], layout: 'total, sizes, prev, pager, next, jumper', pagerCount: 5 })
const emit = defineEmits<{ 'update:currentPage': [value: number]; 'update:pageSize': [value: number]; 'current-change': [value: number]; 'size-change': [value: number] }>()
const jump = ref<string | number>('')
const pages = computed(() => Math.max(1, Math.ceil(props.total / Math.max(1, props.pageSize))))
const current = computed(() => Math.min(pages.value, Math.max(1, props.currentPage)))
const narrow = useMediaQuery('(max-width: 640px)')
const siblings = computed(() => narrow.value ? 0 : Math.max(0, Math.floor((props.pagerCount - 3) / 2)))
function has(part: string) { return props.layout.split(',').map(value => value.trim()).includes(part) }
function page(next: number) { if (props.disabled || !Number.isFinite(next)) return; const value = Math.max(1, Math.min(pages.value, Math.trunc(next))); emit('update:currentPage', value); emit('current-change', value) }
function size(raw: unknown) { const value = Number(raw); if (props.disabled || !Number.isFinite(value) || value <= 0) return; emit('update:pageSize', value); emit('size-change', value) }
</script>
<template>
  <div class="pager">
    <span v-if="has('total')" class="pager__total">共 {{ total }} 条</span>
    <Select v-if="has('sizes')" :model-value="String(pageSize)" :disabled="disabled" @update:model-value="size">
      <SelectTrigger aria-label="每页条数" class="h-8 w-auto min-w-24"><SelectValue /></SelectTrigger>
      <SelectContent><SelectItem v-for="value in pageSizes" :key="value" :value="String(value)">{{ value }} 条 / 页</SelectItem></SelectContent>
    </Select>
    <Pagination :page="current" :total="Math.max(0, total)" :items-per-page="Math.max(1, pageSize)" :sibling-count="siblings" :disabled="disabled" show-edges class="m-0 w-auto" aria-label="分页" @update:page="page">
      <PaginationContent v-slot="{ items }" class="pager__pages">
        <PaginationFirst v-if="has('pager') && current > 1 && !narrow" size="icon-sm" aria-label="第一页"><ChevronsLeft /></PaginationFirst>
        <PaginationPrevious v-if="has('prev')" size="icon-sm" aria-label="上一页"><ChevronLeft /></PaginationPrevious>
        <template v-if="has('pager')">
          <template v-for="(item, index) in items" :key="index">
            <PaginationItem v-if="item.type === 'page'" :value="item.value" :is-active="current === item.value" size="sm" :aria-label="`第 ${item.value} 页`">{{ item.value }}</PaginationItem>
            <PaginationEllipsis v-else aria-label="更多页码" />
          </template>
        </template>
        <PaginationNext v-if="has('next')" size="icon-sm" aria-label="下一页"><ChevronRight /></PaginationNext>
        <PaginationLast v-if="has('pager') && current < pages && !narrow" size="icon-sm" aria-label="最后一页"><ChevronsRight /></PaginationLast>
      </PaginationContent>
    </Pagination>
    <Label v-if="has('jumper')" class="pager__jump">跳至<Input v-model="jump" type="number" :min="1" :max="pages" :disabled="disabled" aria-label="跳转页码" @keydown.enter.prevent="($event.target as HTMLInputElement).blur()" @change="page(Number(jump))" />页</Label>
  </div>
</template>
