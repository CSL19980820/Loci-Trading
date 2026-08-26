<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { UploadFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import {
  importResearchMembershipSnapshots,
  importResearchPointInTimeFacts,
} from '@/shared/api/quant_research'
import type {
  ResearchMembershipSnapshotPayload,
  ResearchPointInTimeFactPayload,
} from '@/shared/types/quant-research'

export type ResearchTemporalImportKind = 'membership' | 'fact'

const props = defineProps<{
  visible: boolean
  kind: ResearchTemporalImportKind
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  imported: [kind: ResearchTemporalImportKind, count: number]
}>()

const raw = ref('')
const error = ref('')
const submitting = ref(false)

const title = computed(() => props.kind === 'membership' ? '导入历史股票池快照' : '导入 PIT 事实')
const hint = computed(() => props.kind === 'membership'
  ? '粘贴快照 JSON 数组；每项必须含历史日期、来源、抓取时间、原始载荷 SHA-256 和解析版本。'
  : '粘贴事实 JSON 数组；每项必须含观察/可见日期、来源、抓取时间、原始载荷 SHA-256 和解析版本。')
const placeholder = computed(() => props.kind === 'membership'
  ? '[{ "universe_id": "...", "as_of": "YYYY-MM-DD", "available_at": "YYYY-MM-DD", "members": [], "source_id": "...", "source_url": "...", "snapshot_revision": "...", "fetched_at": "2026-08-05T09:30:00+08:00", "payload_sha256": "64 位 SHA-256", "parser_revision": "..." }]'
  : '[{ "observation_id": "...", "entity_id": "...", "observed_on": "YYYY-MM-DD", "available_at": "YYYY-MM-DD", "source_id": "...", "source_url": "...", "revision": "...", "fetched_at": "2026-08-05T09:30:00+08:00", "payload_sha256": "64 位 SHA-256", "parser_revision": "..." }]')

watch(() => props.visible, (visible) => {
  if (!visible) return
  raw.value = ''
  error.value = ''
})

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function hasText(value: Record<string, unknown>, key: string): boolean {
  return typeof value[key] === 'string' && Boolean(value[key].trim())
}

function isIsoDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}

function isIsoTimestamp(value: unknown): value is string {
  if (typeof value !== 'string' || !value.includes('T')) return false
  return !Number.isNaN(new Date(value).getTime())
}

function isSha256(value: unknown): value is string {
  return typeof value === 'string' && /^[0-9a-f]{64}$/i.test(value)
}

function isHttpUrl(value: unknown): boolean {
  if (typeof value !== 'string' || !value.trim()) return false
  try {
    const url = new URL(value)
    return url.protocol === 'https:' || url.protocol === 'http:'
  } catch {
    return false
  }
}

function parsedArray(): unknown[] | null {
  try {
    const parsed: unknown = JSON.parse(raw.value)
    if (!Array.isArray(parsed) || !parsed.length) {
      error.value = '请输入至少一条 JSON 数组记录'
      return null
    }
    return parsed
  } catch {
    error.value = '导入内容不是有效 JSON 数组'
    return null
  }
}

function parseMembershipRows(): ResearchMembershipSnapshotPayload[] | null {
  const parsed = parsedArray()
  if (!parsed) return null
  const required = [
    'universe_id', 'as_of', 'available_at', 'source_id', 'source_url', 'snapshot_revision',
    'fetched_at', 'payload_sha256', 'parser_revision',
  ]
  if (!parsed.every((item) => isRecord(item) && required.every((key) => hasText(item, key)))) {
    error.value = '每条历史股票池快照必须包含标识、日期、来源链接、抓取时间、载荷 hash 和解析版本'
    return null
  }
  if (!parsed.every((item) => isRecord(item)
    && isIsoDate(item.as_of)
    && isIsoDate(item.available_at)
    && isIsoTimestamp(item.fetched_at)
    && isSha256(item.payload_sha256)
    && isHttpUrl(item.source_url))) {
    error.value = '历史股票池日期、抓取时间、source_url 和 payload_sha256 必须有效'
    return null
  }
  if (!parsed.every((item) => isRecord(item)
    && Array.isArray(item.members)
    && item.members.length > 0
    && item.members.every((member) => typeof member === 'string' && Boolean(member.trim()))
    && new Set(item.members.map((member) => String(member).trim())).size === item.members.length)) {
    error.value = 'members 必须是非空、无重复的字符串数组，不能用空股票池冒充历史快照'
    return null
  }
  return parsed as ResearchMembershipSnapshotPayload[]
}

function parseFactRows(): ResearchPointInTimeFactPayload[] | null {
  const parsed = parsedArray()
  if (!parsed) return null
  const required = [
    'observation_id', 'entity_id', 'observed_on', 'available_at', 'source_id', 'source_url',
    'revision', 'fetched_at', 'payload_sha256', 'parser_revision',
  ]
  if (!parsed.every((item) => isRecord(item) && required.every((key) => hasText(item, key)))) {
    error.value = '每条 PIT 事实必须包含标识、观察日、可见日、来源链接、抓取时间、载荷 hash 和解析版本'
    return null
  }
  if (!parsed.every((item) => isRecord(item)
    && isIsoDate(item.observed_on)
    && isIsoDate(item.available_at)
    && (!item.published_at || isIsoDate(item.published_at))
    && isIsoTimestamp(item.fetched_at)
    && isSha256(item.payload_sha256)
    && isHttpUrl(item.source_url))) {
    error.value = 'PIT 事实的日期、抓取时间、source_url 和 payload_sha256 必须有效'
    return null
  }
  return parsed as ResearchPointInTimeFactPayload[]
}

function close(): void {
  if (!submitting.value) emit('update:visible', false)
}

function importError(caught: unknown): string {
  const error = caught as Error & { status?: number }
  const message = caught instanceof Error ? caught.message : '没有更多说明'
  if (error.status === 401) return `这次导入没有写入权限，重新登录后原样再提交一次：${message}`
  if (error.status === 422) return `导入内容不符合研究库的格式要求：${message}`
  if (error.status === 503) return '研究库暂时写不进去。保持导入内容不动，过一会儿原样再提交一次'
  return caught instanceof Error ? message : '没导进去，确认本机服务还在运行'
}

async function submit(): Promise<void> {
  error.value = ''
  submitting.value = true
  try {
    if (props.kind === 'membership') {
      const snapshots = parseMembershipRows()
      if (!snapshots) return
      const result = await importResearchMembershipSnapshots({ snapshots })
      emit('imported', 'membership', result.total)
      ElMessage.success(`已导入 ${result.total} 条历史股票池快照`)
    } else {
      const facts = parseFactRows()
      if (!facts) return
      const result = await importResearchPointInTimeFacts({ facts })
      emit('imported', 'fact', result.total)
      ElMessage.success(`已导入 ${result.total} 条 PIT 事实`)
    }
    emit('update:visible', false)
  } catch (caught: unknown) {
    error.value = importError(caught)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    :title="title"
    width="min(92vw, 720px)"
    :close-on-click-modal="false"
    @update:model-value="emit('update:visible', $event)"
    @closed="close"
  >
    <el-alert type="info" show-icon :closable="false" :title="hint" />
    <el-alert v-if="error" class="dialog-alert" type="error" show-icon :closable="false" :title="error" />
    <el-form class="import-form" label-position="top" @submit.prevent="submit">
      <el-form-item label="批量 JSON" required>
        <el-input
          v-model="raw"
          type="textarea"
          :autosize="{ minRows: 10, maxRows: 18 }"
          :placeholder="placeholder"
          spellcheck="false"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button :disabled="submitting" @click="close">取消</el-button>
      <el-button type="primary" :icon="UploadFilled" :loading="submitting" @click="submit">导入并校验</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.dialog-alert { margin-top: .75rem; }
.import-form { margin-top: .8rem; }
</style>
