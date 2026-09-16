<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'

import { useBatchBrowseStore, type OpenBatchInput } from '@/shared/stores/batchBrowse'

const props = withDefaults(
  defineProps<{
    code: string
    name?: string | null
    /** Stop click bubbling (e.g. inside clickable table rows). */
    stop?: boolean
    /** 同批上下文：≥2 只时开切票会话 */
    batch?: Omit<OpenBatchInput, 'focusCode'> | null
    /** 可选覆盖目标 view */
    view?: 'quote'
    date?: string | null
    /** 有名称时是否附带显示代码；窄列表可关 */
    showCode?: boolean
  }>(),
  {
    name: null,
    stop: false,
    batch: null,
    view: undefined,
    date: null,
    showCode: true,
  },
)

const router = useRouter()
const batchStore = useBatchBrowseStore()

function archiveQuery(
  view?: 'quote',
  date?: string | null,
): Record<string, string> | undefined {
  const query: Record<string, string> = {}
  if (view && view !== 'quote') query.view = view
  const d = String(date || '').trim()
  if (/^\d{4}-\d{2}-\d{2}$/.test(d)) query.date = d
  return Object.keys(query).length ? query : undefined
}

const archiveTo = computed(() => ({
  path: `/archive/${props.code}`,
  query: archiveQuery(props.view, props.date),
}))

function onClick(event: MouseEvent): void {
  if (props.stop) event.stopPropagation()
  if (props.batch?.items?.length) {
    batchStore.openBatch({
      ...props.batch,
      focusCode: props.code,
    })
  }
}

/** 供父组件程序化开档（如表行点击）。 */
function openWithBatch(
  input: OpenBatchInput & { view?: 'quote'; date?: string | null },
): void {
  batchStore.openBatch(input)
  void router.push({
    path: `/archive/${input.focusCode}`,
    query: archiveQuery(input.view, input.date),
  })
}

defineExpose({ openWithBatch })
</script>

<template>
  <RouterLink :to="archiveTo" class="stock-link whitespace-nowrap" @click="onClick">
    <template v-if="name">
      {{ name }}
      <span v-if="showCode" class="code">{{ code }}</span>
    </template>
    <template v-else>{{ code }}</template>
  </RouterLink>
</template>
<style scoped>

.stock-link .code {
  margin-left: var(--gap-1);
}
</style>
