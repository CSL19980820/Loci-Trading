<script setup lang="ts">
/**
 * 一条执行记录的失败全文。
 *
 * 为什么要有它：`error_text` 在表格里被 `firstLine()` 截到 90 字，全文只能靠原生
 * `title` 悬停——悬停读不完、读不了多行、也复制不走。排查一次失败得先看半句、
 * 再猜关键词、最后去翻日志。这里把全文摊开并给一个复制按钮，把「看为什么失败」
 * 收成一次点击。
 */
import { computed } from 'vue'
import { toast } from 'vue-sonner'

import { Badge } from '@/shared/components/ui/badge'
import { Button } from '@/shared/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/shared/components/ui/dialog'
import { copyText } from '@/shared/lib/clipboard'
import type { JobRun } from '@/shared/types/quant'

import { cnStrategyName, formatRunDuration, statusLabel, traderJobName, triggerLabel } from '../composables/opsLabels'

const props = defineProps<{
  modelValue: boolean
  run: JobRun | null
}>()

const emit = defineEmits<{
  'update:modelValue': [open: boolean]
}>()

const open = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

const errorText = computed(() => String(props.run?.error_text || '').trim())
const startedAt = computed(() => String(props.run?.started_at || '').replace('T', ' ').slice(0, 19))

/**
 * `job_name` 是后端原样字段：绑定任务长成 `screen:sanyuan-tail-v1`。
 * 弹窗与复制文本都要中文名，别把英文 slug 甩给用户（或甩到群里）。
 */
const jobLabel = computed(() => {
  const run = props.run
  const name = String(run?.job_name || '').trim()
  if (!name) return String(run?.job_id || '—')
  const bound = /^(?:screen|skill):(.+)$/.exec(name)
  return bound ? cnStrategyName('', bound[1]) : traderJobName(run?.kind || '', name)
})

/** 复制时连同时间与任务名一起给出：贴到群里问人时，光有堆栈没人知道是哪条。 */
const copyPayload = computed(() => {
  const run = props.run
  if (!run) return ''
  return [
    `任务：${jobLabel.value}`,
    `运行：${run.id}`,
    `时间：${startedAt.value || '—'}`,
    `结果：${statusLabel(String(run.status || ''))}`,
    '',
    errorText.value || '（后台没有留下原因）',
  ].join('\n')
})

async function copyAll(): Promise<void> {
  if (await copyText(copyPayload.value)) toast.success('已复制失败全文')
  else toast.error('复制失败，请手动选中下面的正文复制')
}
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent class="w-[min(46rem,96vw)] max-w-none gap-[var(--gap-3)] rounded-[var(--radius)] p-[var(--gap-3)] sm:max-w-none">
      <DialogHeader class="gap-1 border-b border-line pb-[var(--gap-3)] text-left">
        <DialogTitle>这次为什么失败</DialogTitle>
      </DialogHeader>

      <div v-if="run" class="run-error">
        <dl class="run-error__meta">
          <div>
            <dt>任务</dt>
            <dd>{{ jobLabel }}</dd>
          </div>
          <div>
            <dt>时间</dt>
            <dd class="mono">{{ startedAt || '—' }}</dd>
          </div>
          <div>
            <dt>触发</dt>
            <dd>{{ triggerLabel(String(run.trigger || '')) }}</dd>
          </div>
          <div>
            <dt>耗时</dt>
            <dd class="mono">{{ formatRunDuration(Number(run.duration_ms ?? 0)) }}</dd>
          </div>
          <div>
            <dt>结果</dt>
            <dd>
              <!-- 成功走状态色 --ok（绿留给价格），失败走印章红，其余是中性档 -->
              <Badge
                v-if="run.status === 'failed'"
                variant="destructive"
              >
                {{ statusLabel(String(run.status || '')) }}
              </Badge>
              <Badge
                v-else-if="run.status === 'success'"
                class="border-transparent bg-ok-soft text-ok"
              >
                {{ statusLabel(String(run.status || '')) }}
              </Badge>
              <Badge v-else variant="secondary">
                {{ statusLabel(String(run.status || '')) }}
              </Badge>
            </dd>
          </div>
          <div>
            <dt>run id</dt>
            <dd class="mono dim">{{ run.id }}</dd>
          </div>
        </dl>

        <pre v-if="errorText" class="run-error__body" data-testid="run-error-body">{{ errorText }}</pre>
        <p v-else class="run-error__empty">后台没有留下原因。可先看这条记录的耗时与触发方式。</p>
      </div>

      <DialogFooter class="border-t border-line pt-[var(--gap-3)] sm:justify-end">
        <Button variant="outline" :disabled="!run" @click="copyAll">复制全文</Button>
        <Button access="read" @click="open = false">关闭</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<style scoped>
.run-error {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  min-width: 0;
}

.run-error__meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 11rem), 1fr));
  gap: var(--gap-2) var(--gap-3);
  padding: var(--gap-3);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--surface-sunken);
  margin: 0;
}

.run-error__meta > div {
  display: flex;
  align-items: baseline;
  gap: 0.4rem;
  min-width: 0;
}

.run-error__meta dt {
  flex: 0 0 auto;
  font-size: 0.76rem;
  color: var(--mist);
}

.run-error__meta dd {
  margin: 0;
  min-width: 0;
  font-size: 0.86rem;
  overflow-wrap: anywhere;
}

.run-error__body {
  margin: 0;
  padding: var(--gap-3);
  max-height: 24rem;
  overflow: auto;
  border: 1px solid color-mix(in oklab, var(--stamp) 30%, var(--rule));
  border-radius: var(--radius);
  background: var(--surface-canvas);
  font-family: var(--mono);
  font-size: var(--fs-aux);
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  /* 可选中：复制按钮失效时（非安全上下文）用户还得能手动选 */
  user-select: text;
}

.run-error__empty {
  margin: 0;
  color: var(--muted);
  font-size: 0.86rem;
}

.mono {
  font-family: var(--mono);
}

.dim {
  color: var(--muted);
}
</style>
