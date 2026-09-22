<script setup lang="ts">
import { computed, ref } from 'vue'
import { ChevronRight, Trash } from '@lucide/vue'

import { Badge } from '@/shared/components/ui/badge'
import { Button } from '@/shared/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/shared/components/ui/dialog'
import EmptyState from '@/shared/components/ui/EmptyState.vue'

import { dialogWidth } from '@/shared/lib/format'
import type { AkshareCatalogCapability } from '@/shared/types/quant'

import SourceDatasetDialog from './SourceDatasetDialog.vue'
import SourceDatasetList from './SourceDatasetList.vue'
import { KIND_LABEL, type MarketPackage } from '../composables/useMarketCatalog'

const props = defineProps<{
  modelValue: boolean
  item: MarketPackage | null
  /** 已装分区才给卸载入口 */
  showRemove?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [boolean]
  open: [item: MarketPackage]
  remove: [item: MarketPackage]
}>()

const open = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

const title = computed(() => props.item?.name || '货品详情')
const kindLabel = computed(() => (props.item ? KIND_LABEL[props.item.kind] : '—'))
const trustLabel = computed(() => (props.item?.trust === 'official' ? '官方' : '本机'))
const versionLabel = computed(() => {
  const raw = props.item?.version || ''
  if (!raw || raw === '—') return '—'
  return raw === 'bundled' ? '内置' : raw
})
const stateLabel = computed(() => (props.item?.enabled === false ? '停用' : '启用'))
const openLabel = computed(() => (props.item?.kind === 'source' ? '数据源' : '工作台'))
const canRemove = computed(() => Boolean(props.showRemove && props.item?.removable))

const datasetOpen = ref(false)
const dataset = ref<AkshareCatalogCapability | null>(null)

function onPickDataset(item: AkshareCatalogCapability): void {
  dataset.value = item
  datasetOpen.value = true
}

function onOpen(): void {
  if (!props.item) return
  emit('open', props.item)
}

function onRemove(): void {
  if (!props.item) return
  emit('remove', props.item)
}
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent
      class="market-detail-dialog max-w-none sm:max-w-none"
      :style="{ width: dialogWidth() }"
    >
      <DialogHeader class="text-left">
        <DialogTitle>{{ title }}</DialogTitle>
      </DialogHeader>
      <div v-if="item" class="market-detail-body">
        <div class="meta-grid">
          <div class="meta-cell"><span class="dim">品类</span><strong>{{ kindLabel }}</strong></div>
          <div class="meta-cell"><span class="dim">信任</span><strong>{{ trustLabel }}</strong></div>
          <div class="meta-cell"><span class="dim">版本</span><strong>{{ versionLabel }}</strong></div>
          <div class="meta-cell">
            <span class="dim">状态</span>
            <Badge v-if="item.enabled === false" variant="secondary">{{ stateLabel }}</Badge>
            <Badge v-else class="border-transparent bg-info-soft text-info-ink">{{ stateLabel }}</Badge>
          </div>
        </div>
        <div v-if="item.kind === 'source'" class="meta-desc">
          <span class="dim">来源地址</span>
          <strong class="url">{{ item.baseUrl || '未登记' }}</strong>
        </div>
        <div class="meta-desc">
          <span class="dim">说明</span>
          <strong>{{ item.description || '—' }}</strong>
        </div>

        <section v-if="item.kind === 'source'" class="section" aria-label="数据列表">
          <SourceDatasetList :source-id="item.slug" @select="onPickDataset" />
        </section>
      </div>
      <EmptyState v-else description="未选择货品" />

      <DialogFooter>
        <Button v-if="canRemove" variant="destructive" @click="onRemove">
          <Trash aria-hidden="true" />
          卸载
        </Button>
        <Button access="read" :disabled="!item" @click="onOpen">
          <ChevronRight aria-hidden="true" />
          {{ openLabel }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>

  <SourceDatasetDialog v-model="datasetOpen" :dataset="dataset" />
</template>

<style scoped>
.market-detail-body { max-height: 68dvh; overflow: auto; overscroll-behavior: contain; }
.meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 9em), 1fr));
  gap: var(--gap-2);
}
.meta-cell,
.meta-desc {
  display: flex;
  flex-direction: column;
  gap: var(--gap-1);
  padding: var(--gap-2);
  min-width: 0;
  align-items: flex-start;
  overflow-wrap: anywhere;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet-alt);
}
.meta-desc { margin-top: var(--gap-2); background: var(--sheet); }
.dim {
  color: var(--mist);
  font-size: var(--fs-aux);
}
.section {
  margin-top: var(--gap-2);
  padding-top: var(--gap-2);
  border-top: 1px solid var(--rule);
}
.url {
  font-family: var(--mono);
  font-size: var(--fs-aux);
  word-break: break-all;
}
</style>
