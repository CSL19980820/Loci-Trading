<script setup lang="ts">
import { computed, reactive, ref } from 'vue'

import {
  downloadSharePack,
  getSharePackStatus,
  type SharePackStatus,
} from '@/shared/api/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
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

const receipt = computed((): ReceiptPair[] => {
  const s = status.value
  if (!s) return [{ key: '版本', value: '—' }]
  return [
    { key: '版本', value: `v${s.version}` },
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
  <SettingsPanel title="一键打包" :receipt="receipt">
    <div class="pack-desk page-scroll">
      <el-alert
        v-if="notice"
        :title="notice"
        type="success"
        show-icon
        closable
        class="pack-alert"
        @close="notice = ''"
      />
      <el-alert
        v-if="errorText"
        :title="errorText"
        type="error"
        show-icon
        closable
        class="pack-alert"
        @close="errorText = ''"
      />

      <section v-if="status" class="pack-manifest" aria-label="分享打包">
        <header class="pack-manifest__head">
          <div>
            <h3 class="pack-manifest__title">
              Loci
              <span class="pack-manifest__ver">v{{ status.version }}</span>
            </h3>
          </div>
          <div class="pack-manifest__stamp" :class="{ 'is-ready': status.can_pack }">
            <span>{{ status.can_pack ? '可封箱' : '缺编译' }}</span>
            <small>{{ status.released_at || '—' }}</small>
          </div>
        </header>

        <p v-if="!status.can_pack" class="pack-block-reason">{{ status.reason }}</p>
        <p v-else class="pack-runtime">
          运行时底座（必含）
          <code>{{ status.bundle_root }}</code>
          · {{ formatBytes(status.runtime_bytes) }}
        </p>

        <EmptyState
          v-if="!status.can_pack"
          description="还没有可分享的编译包"
          reason="先用打包脚本 scripts/build-loci.ps1 打出 Loci.exe 与运行时目录，再回到这里封箱。"
        />

        <template v-else>
          <el-alert
            v-if="personalOn.length"
            type="error"
            show-icon
            :closable="false"
            class="pack-alert"
            :title="`这份包会带走你的${personalOn.join('、')}——只适合自己换机器`"
            description="要发给别人的话，取消这些勾选；其余项默认已抹掉 API Key、Webhook 与纸面交易记录。"
          />
          <el-alert
            v-else
            type="success"
            show-icon
            :closable="false"
            class="pack-alert"
            title="当前是可分享的脱敏包"
            description="运维库与 MCP 只带骨架：任务定义、战法档案、推送模板、调参档位；API Key、Webhook、纸面舱与教训留痕都不会进包。"
          />

          <div class="pack-options" role="group" aria-label="可选附件">
            <label
              v-for="opt in status.options"
              :key="opt.id"
              class="pack-opt"
              :class="{
                'is-off': !opt.available,
                'is-on': selected[opt.id],
                'is-private': selected[opt.id] && (opt.id === 'private' || opt.id === 'ledger'),
              }"
            >
              <el-checkbox
                v-model="selected[opt.id]"
                :disabled="!opt.available"
              >
                <span class="pack-opt__label">{{ opt.label }}</span>
              </el-checkbox>
              <span class="pack-opt__desc">{{ opt.description }}</span>
              <span class="pack-opt__size mono">
                {{ opt.available ? formatBytes(opt.bytes) : '无' }}
              </span>
            </label>
          </div>

          <aside class="pack-seal" aria-label="打包密码">
            <el-form label-position="left" label-width="5.5rem" @submit.prevent>
              <el-form-item label="打包密码" required>
                <el-input
                  v-model="passwordInput"
                  type="password"
                  show-password
                  placeholder="输入打包密码后才能生成"
                  autocomplete="off"
                />
              </el-form-item>
            </el-form>
          </aside>

          <footer class="pack-foot">
            <span class="pack-estimate mono">
              约 {{ formatBytes(estimatedBytes) }}
              <template v-if="lastFile"> · 上次 {{ lastFile }}</template>
            </span>
            <el-button
              type="primary"
              :loading="packing"
              :disabled="!canSubmit"
              @click="packNow"
            >
              生成分享包
            </el-button>
          </footer>
        </template>
      </section>

      <!-- 真空态描述真空，别再写成「正在读取」——加载态由上面的 busy 分支负责 -->
      <EmptyState
        v-else-if="!busy"
        description="还没有打包状态"
        reason="点右上角「刷新」重新读取；若仍为空，说明本机尚未生成过分享包。"
      />
    </div>
  </SettingsPanel>
</template>

<style scoped>
.pack-desk {
  padding: 0;
  min-height: 0;
}

.pack-alert {
  margin: 0.55rem 0.85rem 0;
}

.pack-manifest {
  border: 0;
  background: var(--sheet);
  position: relative;
  min-height: 100%;
}

.pack-manifest__head {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.85rem 1rem 0.65rem;
  border-bottom: 1px dashed var(--rule);
}

.pack-manifest__title {
  margin: 0;
  font-family: var(--font-display);
  font-size: 1.35rem;
  font-weight: 650;
  letter-spacing: 0.02em;
}

.pack-manifest__ver {
  margin-left: 0.35rem;
  font-family: var(--mono);
  font-size: 0.95rem;
  color: var(--seal-ink);
}

.pack-manifest__stamp {
  flex: 0 0 auto;
  align-self: flex-start;
  min-width: 5.5rem;
  padding: 0.45rem 0.55rem;
  border: 1.5px solid color-mix(in srgb, var(--mist) 55%, var(--rule));
  color: var(--mist);
  text-align: center;
  transform: rotate(-4deg);
}

.pack-manifest__stamp.is-ready {
  border-color: var(--seal);
  color: var(--seal-ink);
  background: var(--seal-soft);
}

.pack-manifest__stamp span {
  display: block;
  font-weight: 700;
  font-size: 0.92rem;
  letter-spacing: 0.08em;
}

.pack-manifest__stamp small {
  display: block;
  margin-top: 0.15rem;
  font-family: var(--mono);
  font-size: 0.68rem;
}

.pack-block-reason,
.pack-runtime {
  margin: 0;
  padding: 0.65rem 1rem;
  font-size: 0.82rem;
  color: var(--mist);
  border-bottom: 1px dashed var(--rule);
}

.pack-runtime code {
  font-family: var(--mono);
  font-size: 0.75rem;
  word-break: break-all;
  color: var(--ink);
}

.pack-options {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 0.35rem 0;
  background: var(--rule);
  border-bottom: 1px dashed var(--rule);
}

.pack-opt {
  display: grid;
  grid-template-columns: minmax(7rem, 10rem) 1fr auto;
  gap: 0.5rem 0.75rem;
  align-items: center;
  padding: 0.55rem 1rem;
  background: var(--sheet);
  cursor: pointer;
}

.pack-opt.is-on {
  background: color-mix(in srgb, var(--seal-soft) 70%, var(--sheet));
}

.pack-opt.is-off {
  opacity: 0.55;
  cursor: not-allowed;
}

/* 会带走个人数据的勾选项要一眼看出来 */
.pack-opt.is-private {
  background: color-mix(in srgb, var(--loss) 12%, var(--sheet));
  box-shadow: inset 3px 0 0 var(--loss);
}

.pack-opt__label {
  font-weight: 600;
}

.pack-opt__desc {
  font-size: 0.8rem;
  color: var(--mist);
  line-height: 1.35;
}

.pack-opt__size {
  font-size: 0.72rem;
  color: var(--mist);
  white-space: nowrap;
}

.pack-seal {
  margin: 0.75rem 1rem;
  padding: 0.55rem 0.85rem 0.15rem;
  border: 1px solid var(--rule);
}

.pack-seal :deep(.el-form-item) {
  margin-bottom: 0.45rem;
}

.pack-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.65rem 1rem 0.9rem;
}

.pack-estimate {
  font-size: 0.78rem;
  color: var(--mist);
}

.mono {
  font-family: var(--mono);
}

@media (max-width: 720px) {
  .pack-opt {
    grid-template-columns: 1fr;
    gap: 0.2rem;
  }

  .pack-manifest__head {
    flex-direction: column;
  }

  .pack-manifest__stamp {
    transform: none;
  }

  .pack-foot {
    flex-direction: column;
    align-items: stretch;
  }
}

@media (prefers-reduced-motion: reduce) {
  .pack-manifest__stamp {
    transform: none;
  }
}
</style>
