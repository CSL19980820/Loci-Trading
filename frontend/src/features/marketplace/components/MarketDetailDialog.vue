<script setup lang="ts">
import { computed, ref } from 'vue'

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
  <el-dialog
    v-model="open"
    :title="title"
    :width="dialogWidth()"
    destroy-on-close
    class="market-detail-dialog"
  >
    <template v-if="item">
      <div class="meta-grid">
        <div class="meta-cell"><span class="dim">品类</span><strong>{{ kindLabel }}</strong></div>
        <div class="meta-cell"><span class="dim">信任</span><strong>{{ trustLabel }}</strong></div>
        <div class="meta-cell"><span class="dim">版本</span><strong>{{ versionLabel }}</strong></div>
        <div class="meta-cell"><span class="dim">状态</span><strong>{{ stateLabel }}</strong></div>
      </div>
      <p class="slug">{{ item.id }}</p>
      <div v-if="item.kind === 'source'" class="meta-desc">
        <span class="dim">来源地址</span>
        <strong class="url">{{ item.baseUrl || '未登记' }}</strong>
      </div>
      <div class="meta-desc">
        <span class="dim">说明</span>
        <strong>{{ item.description || '—' }}</strong>
      </div>

      <section v-if="item.kind === 'source'" class="section" aria-label="数据列表">
        <div class="section-title">数据列表</div>
        <SourceDatasetList :source-id="item.slug" @select="onPickDataset" />
      </section>
    </template>

    <template #footer>
      <el-button v-if="canRemove" type="danger" plain @click="onRemove">卸载</el-button>
      <el-button type="primary" :disabled="!item" @click="onOpen">{{ openLabel }}</el-button>
    </template>

    <SourceDatasetDialog v-model="datasetOpen" :dataset="dataset" />
  </el-dialog>
</template>

<style scoped>
.meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.35rem 0.75rem;
}
.meta-cell,
.meta-desc {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  padding: 0.45rem 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.dim {
  color: var(--mist);
  font-size: 0.76rem;
}
.slug {
  margin: 0.45rem 0 0;
  font-family: var(--mono);
  font-size: 0.72rem;
  color: var(--mist);
}
.section {
  margin-top: 1rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--el-border-color-lighter);
}
.section-title {
  font-size: 0.82rem;
  font-weight: 600;
}
.url {
  font-family: var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  font-size: 0.8rem;
  word-break: break-all;
}
</style>
