<script setup lang="ts">
import { toast } from 'vue-sonner'
import { default as DialogPanel } from '@/shared/components/ui/app/DialogPanel.vue'
import { default as HintTooltip } from '@/shared/components/ui/app/HintTooltip.vue'
import { default as TextField } from '@/shared/components/ui/app/TextField.vue'
import { Notice, StatusBadge } from '@/shared/components/ui/app/presentation'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'

/**
 * 克隆包 → 本地战法的「确认导入」对话框。两处共用：
 *
 * - 调用方已经拿到 `bundle`（例如从别处导出的对象）：直接传 `bundle` prop。
 * - 工坊「战法」Tab 点【从克隆包导入】：不传 `bundle`，开 `paste` 让用户自己贴 JSON。
 *
 * 为什么要有确认这一步而不是点了就建：克隆包里**没有** `ScreenSkillManifest`
 * （见 `shared/lib/cloneBundle.ts` 的头注释），runtime / min_bars / 输出信号全是推断出来的。
 * 用户有权在写进自己工坊之前看清楚「哪些是原作者的、哪些是我们猜的」。
 *
 * 换算逻辑全在纯函数 `planBundleImport()` 里，这里只管取本地 slug、渲染、发请求。
 */
import { computed, ref, watch } from 'vue'


import { createScreenSkill, getScreenSkills } from '@/shared/api/quant_strategy'
import { copyText } from '@/shared/lib/clipboard'
import {
  parseCloneBundleText,
  planBundleImport,
  type BundleImportPlan,
} from '@/shared/lib/cloneBundle'
import { toErrorMessage } from '@/shared/lib/errors'
import { dialogWidth, entryTimingLabel } from '@/shared/lib/format'
import type { CloneBundle } from '@/shared/lib/cloneBundle'
import type { ScreenSkillDetail } from '@/shared/types/quant'

/** 源码预览行数：足够看出「是不是我要的那份」，又不至于把对话框撑爆。 */
const PREVIEW_LINES = 20

const props = withDefaults(
  defineProps<{
    /** 详情页克隆来的包；粘贴模式下为 null。 */
    bundle?: CloneBundle | null
    /** 允许在对话框里直接粘 JSON（工坊入口）。 */
    paste?: boolean
  }>(),
  { bundle: null, paste: false },
)

const visible = defineModel<boolean>({ default: false })

const emit = defineEmits<{ imported: [detail: ScreenSkillDetail] }>()

const existingSlugs = ref<string[]>([])
const slugsBusy = ref(false)
const slugsNote = ref('')
const pasteText = ref('')
const importing = ref(false)
const importError = ref('')

/** 粘贴模式下的解析结果；空输入不算错误，只是还没开始。 */
const parsed = computed(() =>
  pasteText.value.trim() ? parseCloneBundleText(pasteText.value) : null,
)
const parseError = computed(() => (parsed.value && !parsed.value.ok ? parsed.value.error : ''))

const bundle = computed<CloneBundle | null>(() => {
  if (props.bundle) return props.bundle
  return parsed.value?.ok ? parsed.value.bundle : null
})

const plan = computed<BundleImportPlan | null>(() =>
  bundle.value ? planBundleImport(bundle.value, existingSlugs.value) : null,
)

const sourceText = computed(() => String(bundle.value?.source_text ?? ''))

const sourcePreview = computed(() => {
  const lines = sourceText.value.split(/\r?\n/)
  const head = lines.slice(0, PREVIEW_LINES).join('\n')
  if (lines.length <= PREVIEW_LINES) return head
  return `${head}\n…（共 ${lines.length} 行，这里只显示前 ${PREVIEW_LINES} 行）`
})

const runtimeLabel = computed(() => {
  const payload = plan.value?.payload
  if (!payload) return '—'
  return payload.runtime === 'python'
    ? `Python 脚本（入口 ${payload.entrypoint || 'strategy.py:compute'}）`
    : `公式（方言 ${payload.dialect || 'loci'}）`
})

/** 正文为空时后端必拒（`code`/`formula` 的 `min_length=1`），与其 422 不如先拦住并说清。 */
const blocked = computed(() => {
  if (!plan.value) return '还没有可导入的克隆包'
  if (!sourceText.value.trim()) return '克隆包没有正文，导入会被后端拒绝'
  return ''
})

async function loadSlugs(): Promise<void> {
  slugsBusy.value = true
  slugsNote.value = ''
  try {
    existingSlugs.value = (await getScreenSkills()).map((item) => item.slug)
  } catch (caught) {
    // 读不到本地列表不该挡住导入：去重会失准，但后端还有一道唯一性校验兜底。
    existingSlugs.value = []
    slugsNote.value =
      `没读到本地战法列表（${toErrorMessage(caught, '请求失败')}），`
      + 'slug 去重这一步失效了；万一撞名，后端会拒绝并告诉你。'
  } finally {
    slugsBusy.value = false
  }
}

watch(visible, (open) => {
  if (!open) return
  importError.value = ''
  if (!props.bundle) pasteText.value = ''
  void loadSlugs()
})

async function runImport(): Promise<void> {
  const current = plan.value
  if (!current || blocked.value) return
  importing.value = true
  importError.value = ''
  try {
    const detail = await createScreenSkill(current.payload)
    toast.success(
      `已导入到工坊：${detail?.name || current.payload.name}（${detail?.slug || current.payload.slug}）`,
    )
    emit('imported', detail)
    visible.value = false
  } catch (caught) {
    // 后端原文必须原样带出来。slug 冲突、公式编译不过、配额不够，三种的处置完全不同；
    // 一句「操作没成功」等于让用户自己猜，那正是这次要修掉的死路。
    importError.value = toErrorMessage(caught, '导入失败，但后端没说原因')
  } finally {
    importing.value = false
  }
}

/** 高级用户的旧路径：把原始 bundle 抄走，自己处置。 */
async function copyJson(): Promise<void> {
  if (!bundle.value) return
  const ok = await copyText(JSON.stringify(bundle.value, null, 2))
  if (ok) toast.success('已复制克隆包 JSON')
  else toast.warning('剪贴板不可用（非 HTTPS 环境常见），请手工选中下面的正文复制')
}
</script>

<template>
  <DialogPanel
    v-model="visible"
    title="导入克隆包到我的工坊"
    :width="dialogWidth()"
    append-to-body
    destroy-on-close
  >
    <template v-if="paste && !props.bundle">
      <!-- 那段「贴什么进来」的介绍收进 tooltip：placeholder 已经把 JSON 形状摆出来了 -->
      <HintTooltip
        placement="top-start"
        content="粘贴别人导出克隆包时复制给你的那一整段 JSON（一个 publish_id 对象），要粘全"
      >
        <TextField
          v-model="pasteText"
          type="textarea"
          :rows="6"
          placeholder='{ "publish_id": "...", "slug": "...", "source_text": "..." }'
          class="mb"
        />
      </HintTooltip>
      <Notice
        v-if="parseError"
        :title="parseError"
        tone="error"
        show-icon
        :closable="false"
        class="mb"
      />
    </template>

    <Notice
      v-if="slugsNote"
      :title="slugsNote"
      tone="warning"
      show-icon
      :closable="false"
      class="mb"
    />
    <Notice
      v-if="importError"
      :title="importError"
      tone="error"
      show-icon
      class="mb"
      @close="importError = ''"
    />

    <template v-if="plan">
      <h4 class="section">将要创建</h4>
      <div class="spec">
        <div class="spec__row">
          <span class="spec__k">slug</span>
          <span class="mono">
            {{ plan.payload.slug }}
            <StatusBadge v-if="plan.slugRenamed" size="small" tone="warning" effect="plain"
              >已改名</StatusBadge
            >
          </span>
        </div>
        <div class="spec__row">
          <span class="spec__k">名称</span>
          <span>{{ plan.payload.name }}</span>
        </div>
        <div class="spec__row">
          <span class="spec__k">运行时</span>
          <span>{{ runtimeLabel }}</span>
        </div>
        <div class="spec__row">
          <span class="spec__k">入场时点</span>
          <span>{{ entryTimingLabel(plan.payload.manifest.entry_timing) }}</span>
        </div>
        <div class="spec__row">
          <span class="spec__k">最少 K 线</span>
          <span class="mono">{{ plan.payload.manifest.min_bars }}</span>
        </div>
        <div class="spec__row">
          <span class="spec__k">输出信号</span>
          <span class="mono">{{ plan.payload.manifest.output.signal }}</span>
        </div>
        <div class="spec__row">
          <span class="spec__k">参数</span>
          <span class="mono">{{ Object.keys(plan.payload.manifest.params).length }} 个</span>
        </div>
      </div>

      <h4 class="section">这些东西没跟过来 / 是猜的（{{ plan.warnings.length }} 条）</h4>
      <ul class="warnings">
        <li v-for="(item, index) in plan.warnings" :key="index">{{ item }}</li>
      </ul>

      <h4 class="section">正文预览</h4>
      <pre v-if="sourceText.trim()" class="source mono">{{ sourcePreview }}</pre>
      <p v-else class="hint">这份克隆包没有正文。</p>
    </template>

    <template #footer>
      <ActionButton access="read" size="small" @click="visible = false">取消</ActionButton>
      <ActionButton access="read" size="small" :disabled="!bundle" @click="copyJson">只复制 JSON</ActionButton>
      <ActionButton
        size="small"
        tone="primary"
        :busy="importing"
        :disabled="Boolean(blocked) || slugsBusy"
        :title="blocked"
        @click="runImport"
      >
        {{ blocked || '导入到我的工坊' }}
      </ActionButton>
    </template>
  </DialogPanel>
</template>

<style scoped>
.mb {
  margin-bottom: 0.65rem;
}

.hint {
  margin: 0 0 0.6rem;
  color: var(--mist);
  font-size: var(--fs-aux);
  line-height: 1.6;
}

.section {
  margin: 0.9rem 0 0.4rem;
  font-size: 0.86rem;
}

.spec {
  display: grid;
  gap: 0.3rem;
  font-size: var(--fs-body);
}

.spec__row {
  display: flex;
  gap: 0.6rem;
  align-items: baseline;
}

.spec__k {
  flex: 0 0 5.5rem;
  color: var(--mist);
}

.warnings {
  margin: 0;
  padding-left: 1.1rem;
  display: grid;
  gap: 0.35rem;
  font-size: var(--fs-aux);
  line-height: 1.6;
}

.source {
  margin: 0;
  padding: 0.6rem 0.75rem;
  max-height: 16rem;
  overflow: auto;
  background: var(--sheet-alt);
  border: 1px solid var(--rule);
  border-radius: 4px;
  font-size: var(--fs-aux);
  line-height: 1.5;
  white-space: pre;
}

.mono {
  font-variant-numeric: tabular-nums;
}
</style>
