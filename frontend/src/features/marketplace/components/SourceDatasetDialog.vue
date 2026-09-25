<script setup lang="ts">
import { Spinner } from '@/shared/components/ui/spinner'
import { computed, onScopeDispose, reactive, ref, watch } from 'vue'
import { Download, Play, TriangleAlert, Upload } from '@lucide/vue'

import { probeAkshareCatalog } from '@/shared/api/quant'
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import { Badge } from '@/shared/components/ui/badge'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import { Button } from '@/shared/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/shared/components/ui/dialog'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { Input } from '@/shared/components/ui/input'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import { toErrorMessage } from '@/shared/lib/errors'
import { dialogWidth } from '@/shared/lib/format'
import type { AkshareCatalogCapability, ColumnGloss } from '@/shared/types/quant'

const props = defineProps<{
  modelValue: boolean
  dataset: AkshareCatalogCapability | null
}>()

const emit = defineEmits<{
  'update:modelValue': [boolean]
}>()

const open = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

/** 入参取值：预填目录给的样例，用户可改后再取出参 */
const values = reactive<Record<string, string>>({})
const probing = ref(false)
const probeError = ref('')
const columns = ref<ColumnGloss[]>([])
const probed = ref(false)
let probeToken = 0

onScopeDispose(() => {
  probeToken += 1
})

const title = computed(() => props.dataset?.name || '子数据')

const paramRows = computed(() => {
  const list = props.dataset?.parameters || []
  const docs = props.dataset?.param_docs || {}
  return list.map((p) => ({
    name: p.name,
    doc: docs[p.name] || '',
    required: p.required,
    annotation: p.annotation || '',
  }))
})

const parameterRows = computed(() => paramRows.value as unknown as Record<string, unknown>[])
const columnRows = computed(() => columns.value as unknown as Record<string, unknown>[])

const paramColumns: BasicTableColumn[] = [
  { prop: 'name', label: '参数', minWidth: 130, align: 'center', headerAlign: 'center', slotName: 'name' },
  { prop: 'doc', label: '说明', minWidth: 150, align: 'center', headerAlign: 'center', slotName: 'doc' },
  { prop: 'required', label: '必填', width: 70, align: 'center', headerAlign: 'center', slotName: 'required' },
  { prop: 'value', label: '取值', minWidth: 140, align: 'center', headerAlign: 'center', slotName: 'value' },
]

const columnColumns: BasicTableColumn[] = [
  { prop: 'cn', label: '中文名', minWidth: 140, align: 'center', headerAlign: 'center', slotName: 'cn' },
  { prop: 'en', label: '英文名', minWidth: 140, align: 'center', headerAlign: 'center', slotName: 'en' },
]

function seed(): void {
  for (const key of Object.keys(values)) delete values[key]
  for (const p of props.dataset?.parameters || []) {
    const raw = p.sample ?? p.default
    values[p.name] = raw === null || raw === undefined ? '' : String(raw)
  }
}

/** 目录里的样例保留了原始标量类型，回填时别把数字变成字符串。 */
function typedValue(name: string, text: string): string | number | boolean {
  const spec = (props.dataset?.parameters || []).find((p) => p.name === name)
  const origin = spec?.sample ?? spec?.default
  if (typeof origin === 'number' && text.trim() !== '' && !Number.isNaN(Number(text))) {
    return Number(text)
  }
  if (typeof origin === 'boolean') return text === 'true'
  return text
}

async function runProbe(): Promise<void> {
  const dataset = props.dataset
  if (!dataset) return
  const token = ++probeToken
  const datasetName = dataset.name
  probing.value = true
  probeError.value = ''
  try {
    const params: Record<string, unknown> = {}
    for (const [name, text] of Object.entries(values)) {
      if (text === '') continue
      params[name] = typedValue(name, text)
    }
    const result = await probeAkshareCatalog(datasetName, params)
    if (token !== probeToken) return
    if (result.error) {
      probeError.value = result.error
      columns.value = []
    } else {
      columns.value = result.columns_detail
        ?? (result.columns || []).map((raw) => ({ raw, cn: raw, en: '' }))
    }
    probed.value = true
  } catch (caught: unknown) {
    if (token !== probeToken) return
    probeError.value = toErrorMessage(caught, '取出参失败')
    columns.value = []
  } finally {
    if (token === probeToken) probing.value = false
  }
}

watch(
  () => [props.modelValue, props.dataset?.name] as const,
  ([opened]) => {
    probeToken += 1
    probing.value = false
    if (!opened || !props.dataset) return
    seed()
    columns.value = []
    probeError.value = ''
    probed.value = false
    // 无必填参数的接口直接取一次，省一步点击
    if (props.dataset.status === 'available') void runProbe()
  },
  { immediate: true },
)
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent
      class="dataset-dialog max-w-none sm:max-w-none"
      :style="{ width: dialogWidth() }"
    >
      <DialogHeader class="text-left">
        <DialogTitle>{{ title }}</DialogTitle>
      </DialogHeader>
      <div v-if="dataset" class="dataset-body">
        <p class="purpose">{{ dataset.summary || '上游未写说明' }}</p>

        <div class="block">
          <!-- 入参 / 出参是弹窗里并列的两块，标题必须留着区分；但不让它空占一行：
               和出参那行一样，条数读数压到同一行上 -->
          <div class="block-head">
            <span class="block-title"><Upload aria-hidden="true" />入参</span>
            <span class="block-count">{{ paramRows.length }} 项</span>
          </div>
          <BasicTable
            :columns="paramColumns"
            :data-source="parameterRows"
            :pagination="false"
            row-key="name"
            empty-text="该接口不需要入参"
          >
            <template #name="{ row }"><span class="mono">{{ row.name }}</span></template>
            <template #doc="{ row }">
              <Tooltip :delay-duration="150" :disabled="!row.doc">
                <TooltipTrigger as-child>
                  <span class="doc-clip">{{ row.doc || '—' }}</span>
                </TooltipTrigger>
                <TooltipContent>{{ row.doc || '—' }}</TooltipContent>
              </Tooltip>
            </template>
            <template #required="{ row }">
              <Badge
                v-if="row.required"
                variant="outline"
                class="border-transparent bg-warn-soft text-warn-ink"
              >
                是
              </Badge>
              <Badge v-else variant="outline" class="border-line bg-sunken text-mist">否</Badge>
            </template>
            <template #value="{ row }">
              <Input
                :model-value="values[String(row.name)]"
                :placeholder="String(row.annotation || '')"
                :aria-label="`${row.name} 取值`"
                @update:model-value="(next: string | number) => { values[String(row.name)] = String(next) }"
              />
            </template>
          </BasicTable>
        </div>

        <div class="block">
          <div class="block-head">
            <span class="block-title"><Download aria-hidden="true" />出参</span>
            <Button variant="outline" size="sm" :disabled="probing" @click="runProbe">
              <Spinner
                v-if="probing"
                class="animate-spin motion-reduce:animate-none"
                aria-hidden="true"
              />
              <Play v-else aria-hidden="true" />
              取出参
            </Button>
          </div>
          <p v-if="dataset.returns" class="dim declared">上游声明：{{ dataset.returns }}</p>
          <Alert v-if="probeError" class="mb border-warn bg-warn-soft text-warn-ink">
            <TriangleAlert aria-hidden="true" />
            <AlertTitle class="line-clamp-none">{{ probeError }}</AlertTitle>
          </Alert>
          <BasicTable
            v-else-if="columns.length"
            :columns="columnColumns"
            :data-source="columnRows"
            :loading="probing"
            :pagination="false"
            height="14rem"
            row-key="raw"
            empty-text="此次未返回字段"
          >
            <template #cn="{ row }">{{ row.cn || '—' }}</template>
            <template #en="{ row }">
              <span v-if="row.en" class="mono">{{ row.en }}</span>
              <span v-else class="dim">本仓未归一</span>
            </template>
          </BasicTable>
          <PageBusy v-else-if="probing" label="正在读取出参…" />
          <EmptyState v-else :description="probed ? '此次未返回字段' : '尚未读取出参'" :reason="probed ? '' : '点击取出参运行接口'" />
        </div>
      </div>
      <EmptyState v-else description="未选择接口" />
    </DialogContent>
  </Dialog>
</template>

<style scoped>
.dataset-body { max-height: 68dvh; overflow: auto; overscroll-behavior: contain; }
.purpose {
  margin: 0 0 var(--gap-2);
  font-size: var(--fs-aux);
  line-height: 1.5;
  color: var(--muted);
}
.block {
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  overflow: hidden;
}
.block + .block { margin-top: var(--gap-2); }
.block-title {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-2);
  font-size: var(--fs-aux);
  font-weight: 600;
}
.block-count {
  font: var(--fs-aux)/1.2 var(--mono);
  font-variant-numeric: tabular-nums;
  color: var(--mist);
}
.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-2);
  padding: var(--gap-2);
  background: var(--sheet-alt);
  border-bottom: 1px solid var(--rule);
}
.declared {
  margin: var(--gap-2);
}
.mb {
  margin-bottom: var(--gap-2);
}
.mono {
  font-family: var(--mono);
  font-size: var(--fs-aux);
}

.doc-clip {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}
.dim {
  color: var(--mist);
  font-size: var(--fs-aux);
}
</style>
