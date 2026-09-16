<script setup lang="ts">
import { computed, onScopeDispose, reactive, ref, watch } from 'vue'
import { Download, Upload, VideoPlay } from '@element-plus/icons-vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'

import { probeAkshareCatalog } from '@/shared/api/quant'
import { dialogWidth } from '@/shared/lib/format'
import { toErrorMessage } from '@/shared/lib/errors'
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

const columnRows = computed(() => columns.value as unknown as Record<string, unknown>[])

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
  <el-dialog
    v-model="open"
    :title="title"
    :width="dialogWidth()"
    append-to-body
    destroy-on-close
    class="dataset-dialog"
  >
    <div v-if="dataset" class="dataset-body">
      <p class="purpose">{{ dataset.summary || '上游未写说明' }}</p>

      <div class="block">
        <!-- 入参 / 出参是弹窗里并列的两块，标题必须留着区分；但不让它空占一行：
             和出参那行一样，条数读数压到同一行上 -->
        <div class="block-head">
          <span class="block-title"><el-icon aria-hidden="true"><Upload /></el-icon>入参</span>
          <span class="block-count">{{ paramRows.length }} 项</span>
        </div>
        <el-table :data="paramRows" size="small" row-key="name" empty-text="该接口不需要入参">
          <el-table-column prop="name" label="参数" min-width="130">
            <template #default="{ row }"><span class="mono">{{ row.name }}</span></template>
          </el-table-column>
          <el-table-column label="说明" min-width="150">
            <template #default="{ row }">
              <el-tooltip :content="row.doc || '—'" placement="top" :show-after="150" :disabled="!row.doc">
                <span class="doc-clip">{{ row.doc || '—' }}</span>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column label="必填" width="70">
            <template #default="{ row }">
              <el-tag size="small" :type="row.required ? 'warning' : 'info'" effect="plain">
                {{ row.required ? '是' : '否' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="取值" min-width="140">
            <template #default="{ row }">
              <el-input v-model="values[row.name]" size="small" :placeholder="row.annotation" :aria-label="`${row.name} 取值`" />
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="block">
        <div class="block-head">
          <span class="block-title"><el-icon aria-hidden="true"><Download /></el-icon>出参</span>
          <el-button type="primary" plain size="small" :icon="VideoPlay" :loading="probing" @click="runProbe">取出参</el-button>
        </div>
        <p v-if="dataset.returns" class="dim declared">上游声明：{{ dataset.returns }}</p>
        <el-alert
          v-if="probeError"
          :title="probeError"
          type="warning"
          :closable="false"
          show-icon
          class="mb"
        />
        <el-table
          v-else-if="columns.length"
          v-loading="probing"
          :data="columnRows"
          size="small"
          height="14rem"
          row-key="raw"
        >
          <el-table-column prop="cn" label="中文名" min-width="140">
            <template #default="{ row }">{{ row.cn || '—' }}</template>
          </el-table-column>
          <el-table-column prop="en" label="英文名" min-width="140">
            <template #default="{ row }">
              <span v-if="row.en" class="mono">{{ row.en }}</span>
              <span v-else class="dim">本仓未归一</span>
            </template>
          </el-table-column>
        </el-table>
        <PageBusy v-else-if="probing" label="正在读取出参…" />
        <EmptyState v-else :description="probed ? '此次未返回字段' : '尚未读取出参'" :reason="probed ? '' : '点击取出参运行接口'" />
      </div>
    </div>
    <EmptyState v-else description="未选择接口" />
  </el-dialog>
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
