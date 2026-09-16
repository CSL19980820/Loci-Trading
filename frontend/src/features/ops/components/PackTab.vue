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

/**
 * 清单卡片上那块「Loci v1.x + 封箱印章」删了：版本 / 发布日 / 能不能封箱
 * 都是读数，读数归面板头的回执行，不该在正文里再摆一遍标题。
 */
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
        <!--
          标题「Loci v1.x」与封箱印章一并删除：内容全是读数，已迁到面板头回执
          （版本 / 发布 / 状态 / 运行时）。这里只留一条功能行：封箱状态 chip +
          运行时底座路径与体积；封不了箱时同一行直接说原因。
        -->
        <p class="pack-lead">
          <el-tag
            :type="status.can_pack ? 'success' : 'info'"
            size="small"
            effect="plain"
          >
            {{ status.can_pack ? '可封箱' : '缺编译' }}
          </el-tag>
          <template v-if="status.can_pack">
            <span class="pack-lead__k">运行时底座</span>
            <code>{{ status.bundle_root }}</code>
            <span class="mono">{{ formatBytes(status.runtime_bytes) }}</span>
          </template>
          <span v-else class="pack-lead__reason">{{ status.reason }}</span>
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
            :title="`带走${personalOn.join('、')}，要外发请取消勾选`"
          />
          <el-tooltip
            v-else
            placement="bottom-start"
            content="只带骨架（任务 / 战法 / 模板 / 档位）；密钥与纸面记录不进包"
          >
            <el-tag class="pack-flag" type="success" effect="plain" size="small">
              当前是可分享的脱敏包
            </el-tag>
          </el-tooltip>

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
            <el-form label-position="right" label-width="6.5em" size="small" @submit.prevent>
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
        reason="刷新后重新读取状态"
      />
    </div>
  </SettingsPanel>
</template>

<style scoped>
.pack-desk {
  padding: 0;
  min-height: 0;
  min-width: 0;
}

.pack-alert,
.pack-flag {
  margin: var(--gap-2) var(--gap-3) 0;
}

.pack-manifest {
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  overflow: hidden;
  background: var(--surface);
  position: relative;
}

/* 一条功能行：状态 chip + 运行时底座路径 + 体积（或封不了箱的原因） */
.pack-lead {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-1) var(--gap-2);
  margin: 0;
  padding: var(--gap-2) var(--gap-4);
  font-size: var(--fs-aux);
  color: var(--mist);
  border-bottom: 1px solid var(--rule);
  background: var(--surface-sunken);
}

.pack-lead__k {
  color: var(--muted);
}

.pack-lead code {
  font-family: var(--mono);
  font-size: var(--fs-aux);
  word-break: break-all;
  color: var(--ink);
}

.pack-lead__reason {
  color: var(--seal-ink);
}

.pack-options {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: var(--gap-1) 0;
  background: var(--rule);
  border-bottom: 1px solid var(--rule);
}

.pack-opt {
  display: grid;
  grid-template-columns: minmax(7rem, 10rem) minmax(0, 1fr) auto;
  gap: var(--gap-2) var(--gap-3);
  align-items: center;
  padding: var(--gap-3);
  background: var(--surface);
  cursor: pointer;
}

.pack-opt.is-on {
  background: var(--surface-active);
}

.pack-opt.is-off {
  opacity: 0.55;
  cursor: not-allowed;
}

/* 会带走个人数据的勾选项要一眼看出来：警告底 + 1px 描边（私密不是价格，不用涨红竖条） */
.pack-opt.is-private {
  background: var(--warn-soft);
  border: 1px solid color-mix(in oklab, var(--warn) 35%, var(--rule));
}

.pack-opt__label {
  font-weight: 600;
}

.pack-opt__desc {
  overflow-wrap: anywhere;
  font-size: var(--fs-aux);
  color: var(--mist);
  line-height: 1.35;
}

.pack-opt__size {
  font-size: var(--fs-kicker);
  color: var(--mist);
  white-space: nowrap;
}

.pack-seal {
  margin: var(--gap-3) var(--gap-4);
  padding: var(--gap-2) var(--gap-3) 1px;
  border: 1px solid var(--rule);
}

.pack-seal :deep(.el-form-item) {
  margin-bottom: var(--gap-2);
}

.pack-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-3);
  padding: var(--gap-2) var(--gap-4) var(--gap-3);
}

.pack-estimate {
  overflow-wrap: anywhere;
  font-variant-numeric: tabular-nums;
  font-size: var(--fs-aux);
  color: var(--mist);
}

.mono {
  font-family: var(--mono);
}

@media (max-width: 720px) {
  .pack-opt {
    grid-template-columns: 1fr;
    gap: var(--gap-1);
  }

  .pack-foot {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
