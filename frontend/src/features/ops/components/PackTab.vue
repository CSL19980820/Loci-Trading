<script setup lang="ts">
import { Label } from '@/shared/components/ui/label'
import { Notice } from '@/shared/components/ui/app/presentation'
import { default as TextField } from '@/shared/components/ui/app/TextField.vue'
import { Package, ShieldAlert, ShieldCheck } from '@lucide/vue'

import { computed, reactive, ref } from 'vue'

import {
  downloadSharePack,
  getSharePackStatus,
  type SharePackStatus,
} from '@/shared/api/quant'
import { Button } from '@/shared/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/shared/components/ui/card'
import { Checkbox } from '@/shared/components/ui/checkbox'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import StatCard from '@/shared/components/ui/StatCard.vue'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import { formatBytes } from '../composables/opsLabels'
import { useOpsFeedback } from '../composables/useOpsFeedback'
import SettingsPanel, { type ReceiptPair } from './SettingsPanel.vue'

const emit = defineEmits<{ changed: [] }>()

const { busy, notice, errorText } = useOpsFeedback()
const status = ref<SharePackStatus | null>(null)
const packing = ref(false)
const lastFile = ref('')
const passwordInput = ref('')
const selected = reactive<Record<string, boolean>>({})

/** 版本 / 发布日 / 能不能封箱都是读数，归面板头的回执行。 */
const receipt = computed((): ReceiptPair[] => {
  const s = status.value
  if (!s) return [{ key: '版本', value: '—' }]
  return [
    { key: '版本', value: `v${s.version}` },
    { key: '发布', value: s.released_at || '—' },
    { key: '状态', value: s.can_pack ? '可封箱' : '缺编译', hint: s.reason },
    { key: '运行时', value: s.can_pack ? formatBytes(s.runtime_bytes) : '未编译' },
    {
      key: '可选',
      value: `${s.options.filter((o) => o.available).length}/${s.options.length}`,
    },
  ]
})

const estimatedBytes = computed(() => {
  const s = status.value
  if (!s) return 0
  let total = s.can_pack ? s.runtime_bytes : 0
  for (const opt of s.options) {
    if (selected[opt.id] && opt.available) total += opt.bytes
  }
  return total
})

const selectedCount = computed(() => Object.values(selected).filter(Boolean).length)

const canSubmit = computed(
  () =>
    Boolean(status.value?.can_pack)
    && passwordInput.value.length > 0
    && !packing.value
    && !busy.value,
)

/** 勾了就不再脱敏——密钥与个人记录会原样进包 */
const privateOn = computed(() => selected.private === true)

/** 会带出个人数据的勾选项，用于生成"这份包给谁"的提示 */
const personalOn = computed(() => {
  const names: string[] = []
  if (selected.ledger) names.push('账本')
  if (privateOn.value) names.push('密钥与个人记录')
  return names
})

async function load(): Promise<void> {
  const next = await getSharePackStatus()
  status.value = next
  for (const opt of next.options) {
    if (!(opt.id in selected)) selected[opt.id] = opt.default && opt.available
    if (!opt.available) selected[opt.id] = false
  }
  emit('changed')
}

function toggle(id: string, value: boolean | 'indeterminate'): void {
  selected[id] = value === true
}

async function packNow(): Promise<void> {
  if (!canSubmit.value) return
  packing.value = true
  errorText.value = ''
  notice.value = ''
  try {
    const include = Object.entries(selected)
      .filter(([, on]) => on)
      .map(([id]) => id)
    const result = await downloadSharePack(include, passwordInput.value)
    lastFile.value = result.filename
    notice.value = result.sanitized
      ? `已生成 ${result.filename}（脱敏包，抹掉 ${result.sanitizeCount} 处密钥/个人记录）`
      : `已生成 ${result.filename}（含你的密钥与个人记录，请勿转发他人）`
    emit('changed')
  } catch (caught: unknown) {
    errorText.value = caught instanceof Error ? caught.message : '打包失败'
  } finally {
    packing.value = false
  }
}

defineExpose({ load })
</script>

<template>
  <SettingsPanel
    title="一键打包"
    :receipt="receipt"
  >
    <Notice
      v-if="notice"
      :title="notice"
      tone="success"
      show-icon
      closable
      @close="notice = ''"
    />
    <Notice
      v-if="errorText"
      :title="errorText"
      tone="error"
      show-icon
      closable
      @close="errorText = ''"
    />

    <template v-if="status">
      <div class="stat-strip stat-strip--plain cols-3 pack-stats">
        <StatCard label="运行时底座" :value="status.can_pack ? formatBytes(status.runtime_bytes) : '未编译'" :hint="status.can_pack ? String(status.bundle_root || '') : status.reason">
          <template #icon><Package /></template>
        </StatCard>
        <StatCard label="已勾选附件" :value="selectedCount" :hint="`共 ${status.options.length} 项可选`" />
        <StatCard label="预计体积" :value="formatBytes(estimatedBytes)" :hint="lastFile ? `上次 ${lastFile}` : undefined" />
      </div>

      <EmptyState
        v-if="!status.can_pack"
        description="还没有可分享的编译包"
        reason="先用打包脚本 scripts/build-loci.ps1 打出 Loci.exe 与运行时目录，再回到这里封箱。"
        :icon="Package"
        class="pack-empty"
      />

      <template v-else>
        <Card class="pack-card">
          <CardHeader class="pack-card__head">
            <CardTitle>附件清单</CardTitle>
            
          </CardHeader>
          <div class="pack-options" role="group" aria-label="可选附件">
            <Label
              v-for="opt in status.options"
              :key="opt.id"
              class="pack-opt"
              :class="{
                'is-off': !opt.available,
                'is-on': selected[opt.id],
                'is-private': selected[opt.id] && (opt.id === 'private' || opt.id === 'ledger'),
              }"
            >
              <Checkbox
                :model-value="Boolean(selected[opt.id])"
                :disabled="!opt.available"
                :aria-label="opt.label"
                @update:model-value="(v) => toggle(opt.id, v)"
              />
              <span class="pack-opt__copy">
                <span class="pack-opt__label">{{ opt.label }}</span>
                <span class="pack-opt__desc">{{ opt.description }}</span>
              </span>
              <span class="pack-opt__size">{{ opt.available ? formatBytes(opt.bytes) : '无' }}</span>
            </Label>
          </div>
        </Card>

        <Card class="pack-card">
          <CardHeader class="pack-card__head">
            <CardTitle>封箱</CardTitle>
            <CardDescription>打包密码用于解压；生成后的包请自行保管。</CardDescription>
          </CardHeader>
          <div class="pack-seal">
            <div class="pack-flag" :class="personalOn.length ? 'is-warn' : 'is-ok'" role="status">
              <ShieldAlert v-if="personalOn.length" aria-hidden="true" />
              <ShieldCheck v-else aria-hidden="true" />
              <span v-if="personalOn.length">带走 {{ personalOn.join('、') }}，要外发请取消勾选</span>
              <span v-else>当前是可分享的脱敏包：只带骨架（任务 / 战法 / 模板 / 档位），密钥与纸面记录不进包</span>
            </div>
            <div class="pack-seal__row">
              <Label class="pack-seal__label" for="pack-password">打包密码</Label>
              <TextField
                id="pack-password"
                v-model="passwordInput"
                type="password"
                show-password
                placeholder="输入打包密码后才能生成"
                autocomplete="off"
                class="pack-seal__input"
              />
              <Button size="default" :disabled="!canSubmit" @click="packNow">
                <Package />
                {{ packing ? '正在生成…' : '生成分享包' }}
              </Button>
            </div>
            <p class="pack-estimate">
              约 <strong>{{ formatBytes(estimatedBytes) }}</strong>
              <UiBadge v-if="lastFile" variant="secondary" class="ml-2">上次 {{ lastFile }}</UiBadge>
            </p>
          </div>
        </Card>
      </template>
    </template>

    <!-- 真空态描述真空，别再写成「正在读取」——加载态由上面的 busy 分支负责 -->
    <EmptyState
      v-else-if="!busy"
      description="还没有打包状态"
      reason="刷新后重新读取状态"
      class="pack-empty"
    />
  </SettingsPanel>
</template>

<style scoped>
.pack-stats {
  margin-bottom: 0;
}

.pack-card {
  gap: 0;
  overflow: hidden;
}

.pack-card__head {
  padding: var(--gap-4) var(--gap-4) var(--gap-3);
  border-bottom: 1px solid var(--border-subtle);
}

.pack-empty {
  min-height: 240px;
  border: 1px dashed var(--border-default);
  border-radius: var(--radius-lg);
  background: var(--surface);
}

.pack-options {
  display: flex;
  flex-direction: column;
}

.pack-opt {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--gap-3);
  min-height: 52px;
  padding: var(--gap-3) var(--gap-4);
  border-top: 1px solid var(--border-subtle);
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease);
}

.pack-opt:first-child {
  border-top: 0;
}

.pack-opt:hover {
  background: var(--surface-hover);
}

.pack-opt.is-off {
  opacity: 0.55;
  cursor: not-allowed;
}

.pack-opt.is-private {
  background: var(--warn-soft);
}

.pack-opt__copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.pack-opt__label {
  color: var(--text-primary);
  font-size: var(--fs-ui);
  font-weight: 500;
}

.pack-opt__desc {
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.pack-opt__size {
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-aux);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.pack-seal {
  display: flex;
  flex-direction: column;
  gap: var(--gap-3);
  padding: var(--gap-4);
}

.pack-flag {
  display: flex;
  align-items: flex-start;
  gap: var(--gap-2);
  padding: var(--gap-2) var(--gap-3);
  border-radius: var(--radius);
  font-size: var(--fs-aux);
  line-height: 1.5;
}

.pack-flag :deep(svg) {
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  margin-top: 1px;
}

.pack-flag.is-ok {
  background: var(--ok-soft);
  color: var(--ok);
}

.pack-flag.is-warn {
  background: var(--warn-soft);
  color: var(--warn-ink);
}

.pack-seal__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2) var(--gap-3);
}

.pack-seal__label {
  color: var(--text-secondary);
  font-size: var(--fs-ui);
  font-weight: 500;
}

.pack-seal__input {
  flex: 1 1 220px;
  min-width: 0;
}

.pack-estimate {
  margin: 0;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
  font-variant-numeric: tabular-nums;
}

.pack-estimate strong {
  color: var(--text-primary);
  font-family: var(--mono);
}

@media (max-width: 640px) {
  .pack-opt {
    padding: var(--gap-3);
  }

  .pack-seal__row > :deep(button) {
    flex: 1 1 100%;
    min-height: 40px;
  }
}
</style>
