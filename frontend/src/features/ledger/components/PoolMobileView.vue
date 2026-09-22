<script setup lang="ts">
import { Item } from '@/shared/components/ui/item'
import { Label } from '@/shared/components/ui/label'
import { ref, watch } from 'vue'
import { ChevronLeft, ChevronRight, Ellipsis, ListChecks, Plus, RefreshCw, SlidersHorizontal, Trash2 } from '@lucide/vue'
import MobilePageFrame from '@/shared/components/layout/MobilePageFrame.vue'
import PageTabs from '@/shared/components/ui/PageTabs.vue'
import { Button } from '@/shared/components/ui/button'
import { Checkbox } from '@/shared/components/ui/checkbox'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/shared/components/ui/dropdown-menu'
import { Skeleton } from '@/shared/components/ui/skeleton'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import type { Candidate } from '@/shared/types/palace'

const props = defineProps<{
 rows: Candidate[]; page: number; pages: number; total: number; decision: string; filterCount: number
 busy: boolean; error: string; canWrite: boolean; selectionMode: boolean; selectedIds: string[]
 strategyLabel: (value: string) => string
}>()
const emit = defineEmits<{
 decision: [value: string]; detail: [row: Candidate]; filter: []; refresh: []; record: []; multi: []
 select: [id: string, checked: boolean | 'indeterminate']; delete: []; page: [value: number]
}>()
const frame = ref<InstanceType<typeof MobilePageFrame>>()
watch(() => props.page, () => frame.value?.scrollToTop())
const decisions = [{name:'',label:'全部'},{name:'精选',label:'精选'},{name:'观察',label:'观察'},{name:'落选',label:'落选'}]
function score(value: number | null | undefined) { return value == null || !Number.isFinite(Number(value)) ? '—' : Number(value).toFixed(1) }
</script>
<template>
 <MobilePageFrame ref="frame" title="候选池" class="pool-mobile">
  <template #actions>
   <Button access="read" variant="ghost" size="icon" aria-label="更多筛选" @click="emit('filter')"><SlidersHorizontal /><span v-if="filterCount" class="filter-dot">{{ filterCount }}</span></Button>
   <DropdownMenu><DropdownMenuTrigger as-child><Button access="read" variant="ghost" size="icon" aria-label="候选池操作"><Ellipsis /></Button></DropdownMenuTrigger><DropdownMenuContent align="end">
    <DropdownMenuItem access="read" @select="emit('refresh')"><RefreshCw />刷新候选</DropdownMenuItem>
    <DropdownMenuItem v-if="canWrite" @select="emit('record')"><Plus />记一条候选</DropdownMenuItem>
    <DropdownMenuItem v-if="canWrite" @select="emit('multi')"><ListChecks />{{ selectionMode ? '取消多选' : '多选记录' }}</DropdownMenuItem>
   </DropdownMenuContent></DropdownMenu>
  </template>
  <template #navigation><PageTabs :model-value="decision" :items="decisions" variant="pill" :sticky="false" aria-label="按裁决筛选" @update:model-value="value => emit('decision',value)" /></template>
  <p v-if="error" class="pool-mobile__error" role="alert">{{ error }} <Button access="read" variant="link" @click="emit('refresh')">重试</Button></p>
  <div v-if="busy && !rows.length" class="pool-mobile__loading"><Skeleton v-for="n in 6" :key="n" class="h-20" /></div>
  <div v-else-if="rows.length" class="pool-mobile__list">
   <article v-for="row in rows" :key="row.id" class="pool-mobile-row">
    <Label v-if="canWrite && selectionMode" class="pool-mobile-row__select"><Checkbox :model-value="selectedIds.includes(row.id)" :aria-label="`选择${row.name}`" @update:model-value="value => emit('select',row.id,value)" /></Label>
    <Item as="button" type="button" class="pool-mobile-row__body" :aria-label="`查看${row.name}候选详情`" @click="emit('detail',row)">
     <span class="pool-mobile-row__identity"><b>{{ row.name }}</b><small>{{ row.code }}</small></span>
     <span class="pool-mobile-row__meta"><UiBadge :variant="row.decision === '精选' ? 'info' : row.decision === '观察' ? 'warn' : 'secondary'">{{ row.decision }}</UiBadge><time>{{ row.date }}</time><span>{{ strategyLabel(row.rule_version) }}</span></span>
     <span class="pool-mobile-row__score"><strong>{{ score(row.score) }}</strong><small>评分</small></span>
    </Item>
   </article>
  </div>
  <div v-else class="pool-mobile__empty"><strong>暂无候选</strong><span>当前筛选下没有记录</span><Button access="read" variant="outline" @click="emit('filter')">调整筛选</Button></div>
  <template #footer>
   <div class="pool-mobile__pagination"><span>{{ selectedIds.length ? `已选 ${selectedIds.length} 条` : `共 ${total} 条` }}</span><Button v-if="canWrite && selectedIds.length" variant="soft-destructive" size="sm" @click="emit('delete')"><Trash2 />删除</Button><div><Button access="read" variant="ghost" size="icon" aria-label="上一页候选" :disabled="page <= 1 || busy" @click="emit('page',page-1)"><ChevronLeft /></Button><b>{{ page }} / {{ pages }}</b><Button access="read" variant="ghost" size="icon" aria-label="下一页候选" :disabled="page >= pages || busy" @click="emit('page',page+1)"><ChevronRight /></Button></div></div>
  </template>
 </MobilePageFrame>
</template>
<style scoped>
.pool-mobile :deep(.page-tabs__list) { width:100%; }.pool-mobile :deep(.page-tabs__item) { flex:1; justify-content:center; height:36px; font-size:13px; }
.filter-dot { position:absolute; right:1px; top:2px; border-radius:50%; width:15px; height:15px; line-height:15px; background:var(--seal); color:white; font-size:10px; }
.pool-mobile__loading { display:grid; gap:8px; }.pool-mobile__error { margin:0 0 8px; font-size:13px; color:var(--warn); line-height:1.6; }
.pool-mobile__list { overflow:hidden; border:1px solid var(--border-subtle); border-radius:12px; background:var(--surface); }
.pool-mobile-row { display:flex; align-items:stretch; border-bottom:1px solid var(--border-subtle); min-width:0; }.pool-mobile-row:last-child { border-bottom:0; }
.pool-mobile-row__select { display:grid; place-items:center; flex:none; width:36px; padding-left:4px; }
.pool-mobile-row__body { display:grid; grid-template-columns:minmax(0,1fr) 48px; grid-template-rows:auto auto; align-items:center; gap:7px 7px; min-width:0; width:100%; min-height:80px; padding:13px 12px; border:0; background:transparent; text-align:left; color:var(--text-primary); cursor:pointer; }
.pool-mobile-row__body:active { background:var(--surface-hover); }
.pool-mobile-row__identity { display:flex; align-items:baseline; min-width:0; gap:6px; }.pool-mobile-row__identity b { font-size:15px; font-weight:550; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.pool-mobile-row__identity small { color:var(--text-tertiary); font:11px var(--mono); flex:none; }
.pool-mobile-row__meta { display:flex; align-items:center; gap:5px; min-width:0; grid-column:1; font-size:10px; color:var(--text-tertiary); }.pool-mobile-row__meta time { flex:none; font-variant-numeric:tabular-nums; }.pool-mobile-row__meta>span:last-child { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.pool-mobile-row__meta :deep(.ui-badge) { font-size:10px; padding-inline:5px; }
.pool-mobile-row__score { display:flex; flex-direction:column; align-items:flex-end; grid-column:2; grid-row:1/3; gap:4px; }.pool-mobile-row__score strong { font:600 19px/1.2 var(--font); font-variant-numeric:tabular-nums; }.pool-mobile-row__score small { font-size:10px; color:var(--text-tertiary); }
.pool-mobile__pagination { display:flex; justify-content:space-between; align-items:center; gap:8px; font-size:12px; color:var(--text-tertiary); }.pool-mobile__pagination>div { display:flex; align-items:center; gap:3px; }.pool-mobile__pagination b { min-width:44px; text-align:center; font-size:12px; font-weight:500; color:var(--text-secondary); font-variant-numeric:tabular-nums; }
.pool-mobile__empty { display:flex; flex-direction:column; gap:10px; align-items:center; padding:60px 14px; color:var(--text-tertiary); font-size:13px; }
</style>
