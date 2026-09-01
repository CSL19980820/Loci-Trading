<script setup lang="ts">
import { Picture, Promotion, Stopwatch } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import XSender from 'vue-element-plus-x/es/XSender/index.js'

import {
  applySlashSelection,
  BUILTIN_SLASH_COMMANDS,
  detectSlashTrigger,
  filterSlashSkills,
  type SlashMatch,
  type SlashSkillItem,
} from '../assistantSlash'
import {
  buildContextUsage,
  DEFAULT_CONTEXT_WINDOW,
} from '../assistantContextUsage'
import AssistantContextUsage from './AssistantContextUsage.vue'
import AssistantRuntimeBar, { type ThinkingLevel } from './AssistantRuntimeBar.vue'
import { getSkills } from '@/shared/api/quant'
import type {
  AiAssistantProfile,
  AiMemoryItem,
  AiMessage,
  AiProviderProfile,
  AiToolsCatalog,
} from '@/shared/types/ai_assistant'

type SenderExpose = {
  clear?: () => void
  focus?: (type?: string) => void
  getModelValue?: () => { text?: string; html?: string }
  setText?: (text: string) => void
}

export type AssistantSendPayload = {
  text: string
  images: string[]
  skillSlug?: string
}

const MAX_IMAGES = 4
const MAX_FILE_BYTES = 1_600_000

const props = defineProps<{
  providers: AiProviderProfile[]
  provider: string
  model: string
  thinking: ThinkingLevel
  providerReady: boolean
  busy?: boolean
  waitingUser?: boolean
  sessionLocked?: boolean
  messages?: AiMessage[]
  profile?: AiAssistantProfile | null
  memories?: AiMemoryItem[]
  toolsCatalog?: AiToolsCatalog | null
  observedInputTokens?: number | null
}>()

const emit = defineEmits<{
  send: [payload: AssistantSendPayload]
  cancel: []
  'runtime-select': [payload: { provider: string; model: string }]
  thinking: [level: ThinkingLevel]
  /** 内置斜杠：如 compact */
  'slash-command': [slug: string]
}>()

const senderRef = ref<(InstanceType<typeof XSender> & SenderExpose) | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const pendingText = ref('')
const pendingImages = ref<string[]>([])
const empty = ref(true)
const skills = ref<SlashSkillItem[]>([])
const slashMatch = ref<SlashMatch | null>(null)
const activeSkill = ref<SlashSkillItem | null>(null)
const slashIndex = ref(0)

const slashItems = computed(() => {
  const merged = [...BUILTIN_SLASH_COMMANDS, ...skills.value]
  return slashMatch.value ? filterSlashSkills(merged, slashMatch.value.query) : []
})

const placeholder = computed(() => {
  if (props.waitingUser) return '回复助手以继续…'
  if (!props.providerReady) return '配置模型后即可开始对话'
  return '问持仓… / 激活技能 · Enter 发送 · 可附图'
})

const hint = computed(() => {
  if (props.busy) return '运行中，关闭弹窗也可继续等待'
  if (props.waitingUser) return '等待你的确认'
  if (!props.providerReady) return '模型未配置'
  if (activeSkill.value) return `技能 /${activeSkill.value.slug}`
  return ''
})

const canSend = computed(
  () =>
    props.providerReady
    && !props.busy
    && (!empty.value || pendingImages.value.length > 0 || Boolean(activeSkill.value)),
)

const contextWindow = computed(() => {
  const selected = props.providers.find((item) => item.name === props.provider)
  const catalog = selected?.model_catalog || []
  const hit = catalog.find((item) => item.id === props.model && item.enabled !== false)
  const fromCatalog = Number(hit?.context_window)
  if (Number.isFinite(fromCatalog) && fromCatalog > 0) return fromCatalog
  return DEFAULT_CONTEXT_WINDOW
})

const contextUsage = computed(() => buildContextUsage({
  contextWindow: contextWindow.value,
  systemPromptTokens: props.toolsCatalog?.system_prompt_tokens,
  aboutUser: props.profile?.about_user,
  responseStyle: props.profile?.response_style,
  rules: props.profile?.rules,
  memories: props.profile?.memory_enabled === false ? [] : props.memories,
  tools: props.toolsCatalog?.tools,
  skillText: activeSkill.value
    ? `/${activeSkill.value.slug}\n${activeSkill.value.name}\n${activeSkill.value.description}`
    : '',
  messages: props.messages,
  draftText: pendingText.value,
  observedInputTokens: props.observedInputTokens,
}))

/** 仅当最近助手 warnings 含「已压缩」（由 context_compacted 写入）时展示 */
const compactNotice = computed(() => {
  const rows = props.messages || []
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    const row = rows[i]
    if (!row || row.role !== 'assistant') continue
    const hit = (row.warnings || []).find((text) => String(text).includes('已压缩'))
    return hit ? String(hit) : ''
  }
  return ''
})

function readText(): string {
  return senderRef.value?.getModelValue?.()?.text ?? ''
}

function syncEmpty(): void {
  const text = readText()
  pendingText.value = text.trim()
  empty.value = text.trim().length === 0
  const match = detectSlashTrigger(text)
  slashMatch.value = match
  if (!match) slashIndex.value = 0
  else if (slashIndex.value >= slashItems.value.length) slashIndex.value = 0
}

function clear(): void {
  senderRef.value?.clear?.()
  pendingText.value = ''
  pendingImages.value = []
  empty.value = true
  slashMatch.value = null
  activeSkill.value = null
}

function focus(): void {
  senderRef.value?.focus?.('end')
}

function setText(text: string): void {
  senderRef.value?.setText?.(text)
  pendingText.value = text.trim()
  empty.value = !text.trim()
  void nextTick(() => {
    syncEmpty()
    focus()
  })
}

function clearActiveSkill(): void {
  activeSkill.value = null
}

function pickSkill(item: SlashSkillItem): void {
  const text = readText()
  const match = slashMatch.value ?? detectSlashTrigger(text)
  if (match) {
    const next = applySlashSelection(text, match, '')
    senderRef.value?.setText?.(next)
    pendingText.value = next.trim()
    empty.value = !next.trim()
  }
  slashMatch.value = null
  if (item.builtin) {
    activeSkill.value = null
    emit('slash-command', item.slug)
    void nextTick(() => focus())
    return
  }
  activeSkill.value = item
  void nextTick(() => focus())
}

function onSlashKeydown(event: KeyboardEvent): void {
  if (!slashMatch.value || !slashItems.value.length) return
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    slashIndex.value = (slashIndex.value + 1) % slashItems.value.length
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    slashIndex.value = (slashIndex.value - 1 + slashItems.value.length) % slashItems.value.length
  } else if (event.key === 'Enter' || event.key === 'Tab') {
    const item = slashItems.value[slashIndex.value]
    if (!item) return
    event.preventDefault()
    event.stopPropagation()
    pickSkill(item)
  } else if (event.key === 'Escape') {
    slashMatch.value = null
  }
}

function removeImage(index: number): void {
  pendingImages.value = pendingImages.value.filter((_, i) => i !== index)
}

function openFilePicker(): void {
  if (props.busy || !props.providerReady) return
  fileInput.value?.click()
}

async function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(reader.error ?? new Error('读图失败'))
    reader.readAsDataURL(file)
  })
}

async function addImageFiles(files: FileList | File[]): Promise<void> {
  const list = Array.from(files).filter((f) => f.type.startsWith('image/'))
  if (!list.length) {
    ElMessage.warning('请选择图片文件')
    return
  }
  const room = MAX_IMAGES - pendingImages.value.length
  if (room <= 0) {
    ElMessage.warning(`最多 ${MAX_IMAGES} 张图`)
    return
  }
  const next = [...pendingImages.value]
  for (const file of list.slice(0, room)) {
    if (file.size > MAX_FILE_BYTES) {
      ElMessage.warning(`${file.name} 过大（≤1.5MB）`)
      continue
    }
    try {
      const url = await fileToDataUrl(file)
      if (!url.startsWith('data:image/')) continue
      next.push(url)
    } catch {
      ElMessage.warning(`${file.name} 读取失败`)
    }
  }
  pendingImages.value = next
}

async function onFileChange(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  if (input.files?.length) await addImageFiles(input.files)
  input.value = ''
}

async function onPasteFile(first: File, list: FileList): Promise<void> {
  const files = list?.length ? list : [first]
  await addImageFiles(files)
}

function submit(): void {
  if (slashMatch.value && slashItems.value.length) {
    const item = slashItems.value[slashIndex.value]
    if (item) {
      pickSkill(item)
      return
    }
  }
  const skillSlug = activeSkill.value?.slug
  let text = (pendingText.value || readText()).trim()
  const images = [...pendingImages.value]
  if (!text && skillSlug) text = '按激活技能执行。'
  if ((!text && !images.length) || props.busy || !props.providerReady) return
  clear()
  emit('send', { text, images, ...(skillSlug ? { skillSlug } : {}) })
}

onMounted(() => {
  syncEmpty()
  void getSkills()
    .then((rows) => {
      skills.value = (rows || [])
        .filter((row) => row.enabled !== false)
        .map((row) => ({
          slug: String(row.slug || ''),
          name: String(row.name || row.slug || ''),
          description: String(row.description || ''),
        }))
        .filter((row) => row.slug)
    })
    .catch(() => {
      skills.value = []
    })
})

watch(
  () => props.busy,
  () => {
    /* keep pending text while generating */
  },
)

defineExpose({ clear, focus, setText, getText: () => pendingText.value || readText() })
</script>

<template>
  <div
    class="assistant-sender"
    :class="{ 'is-generating': busy, 'is-locked': sessionLocked || !providerReady }"
    data-testid="assistant-sender"
    @keydown="onSlashKeydown"
  >
    <div v-if="activeSkill" class="assistant-sender__skill" data-testid="assistant-active-skill">
      <el-tag size="small" effect="plain" type="primary" closable @close="clearActiveSkill">
        /{{ activeSkill.slug }} · {{ activeSkill.name }}
      </el-tag>
    </div>
    <div
      v-if="slashMatch && slashItems.length"
      class="assistant-sender__slash"
      data-testid="assistant-slash-menu"
      role="listbox"
      aria-label="技能"
    >
      <el-button
        v-for="(item, index) in slashItems"
        :key="item.slug"
        class="assistant-sender__slash-item"
        :class="{ 'is-active': index === slashIndex }"
        text
        role="option"
        :aria-selected="index === slashIndex"
        @mousedown.prevent="pickSkill(item)"
      >
        <span class="assistant-sender__slash-copy">
          <strong>/{{ item.slug }}</strong>
          <span>{{ item.name }}</span>
          <small v-if="item.description">{{ item.description }}</small>
        </span>
      </el-button>
    </div>
    <div v-if="pendingImages.length" class="assistant-sender__previews" data-testid="assistant-image-previews">
      <div
        v-for="(src, index) in pendingImages"
        :key="`${index}-${src.slice(0, 32)}`"
        class="assistant-sender__preview"
      >
        <img :src="src" alt="待发送图片" />
        <el-button
          class="assistant-sender__preview-remove"
          type="danger"
          circle
          size="small"
          aria-label="移除图片"
          @click="removeImage(index)"
        >
          ×
        </el-button>
      </div>
    </div>
    <XSender
      ref="senderRef"
      class="assistant-sender__x"
      :class="{ 'has-sender-bar': true, 'is-generating': busy }"
      :placeholder="placeholder"
      submit-type="enter"
      variant="default"
      clearable
      :loading="false"
      :disabled="busy || !providerReady"
      :max-length="12000"
      @submit="submit"
      @change="syncEmpty"
      @paste-file="onPasteFile"
    />
    <div class="assistant-sender__bar">
      <div class="assistant-sender__bar-left">
        <el-tooltip content="上传图片">
          <el-button
            circle
            size="small"
            :icon="Picture"
            :disabled="busy || !providerReady || pendingImages.length >= MAX_IMAGES"
            aria-label="上传图片"
            data-testid="assistant-attach-image"
            @click="openFilePicker"
          />
        </el-tooltip>
        <input
          ref="fileInput"
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          multiple
          class="assistant-sender__file"
          @change="onFileChange"
        >
        <AssistantRuntimeBar
          :providers="providers"
          :provider="provider"
          :model="model"
          :thinking="thinking"
          :disabled="Boolean(sessionLocked) || !providers.length"
          @select="emit('runtime-select', $event)"
          @thinking="emit('thinking', $event)"
        />
      </div>
      <div class="assistant-sender__actions">
        <AssistantContextUsage :usage="contextUsage" :compact-notice="compactNotice" />
        <span class="assistant-sender__hint" aria-live="polite">{{ hint }}</span>
        <el-tooltip v-if="busy || waitingUser" :content="waitingUser ? '取消等待并中止' : '中止运行'">
          <el-button
            type="warning"
            circle
            :icon="Stopwatch"
            :aria-label="waitingUser ? '取消等待' : '中止运行'"
            @click="emit('cancel')"
          />
        </el-tooltip>
        <el-tooltip v-if="!busy" :content="waitingUser ? '回复并继续' : '发送 · Shift+Enter 换行'">
          <el-button
            type="primary"
            circle
            :icon="Promotion"
            :disabled="!canSend"
            :aria-label="waitingUser ? '回复并继续' : '发送消息'"
            @click="submit"
          />
        </el-tooltip>
      </div>
    </div>
  </div>
</template>

<style scoped src="./AssistantSenderDock.css"></style>
