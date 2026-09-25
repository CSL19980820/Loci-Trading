<script setup lang="ts">
import { ArrowUp, ImagePlus, Sparkles, Square, X } from '@lucide/vue'
import { toast } from 'vue-sonner'
import { computed, nextTick, onMounted, ref, useId, watch } from 'vue'

import { Button } from '@/shared/components/ui/button'
import { Command, CommandItem, CommandList } from '@/shared/components/ui/command'
import { InputGroup, InputGroupAddon } from '@/shared/components/ui/input-group'
import { Attachment, AttachmentMedia, AttachmentAction, AttachmentActions, AttachmentGroup } from '@/shared/components/ui/attachment'
import { Textarea } from '@/shared/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'

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

export type AssistantSendPayload = {
  text: string
  images: string[]
  skillSlug?: string
}

const MAX_IMAGES = 4
const MAX_FILE_BYTES = 1_600_000
/** 与旧 XSender 的 `max-length` 一致 */
const MAX_TEXT_LENGTH = 12_000

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

/** 输入框本体；对外暴露的 clear / focus / setText / getText 都作用在它上面 */
const inputRef = ref<InstanceType<typeof Textarea> | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const draft = ref('')
const pendingText = ref('')
const pendingImages = ref<string[]>([])
const empty = ref(true)
const skills = ref<SlashSkillItem[]>([])
const slashMatch = ref<SlashMatch | null>(null)
const activeSkill = ref<SlashSkillItem | null>(null)
const slashIndex = ref(0)
const slashId = useId()

const slashItems = computed(() => {
  const merged = [...BUILTIN_SLASH_COMMANDS, ...skills.value]
  return slashMatch.value ? filterSlashSkills(merged, slashMatch.value.query) : []
})

const placeholder = computed(() => {
  if (props.waitingUser) return '回复助手以继续…'
  if (!props.providerReady) return '配置模型后即可开始对话'
  return '输入问题，或用 / 选择技能'
})

const hint = computed(() => {
  if (props.busy) return '运行中'
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
  return draft.value
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
  draft.value = ''
  pendingText.value = ''
  pendingImages.value = []
  empty.value = true
  slashMatch.value = null
  activeSkill.value = null
}

function focus(): void {
  // Textarea 是 SFC 组件，`$el` 才是真正的 <textarea>
  const el = (inputRef.value as unknown as { $el?: unknown } | null)?.$el
  if (!(el instanceof HTMLTextAreaElement)) return
  el.focus()
  // 旧 `focus('end')`：光标落到文末，填入范例后可以接着改
  const end = el.value.length
  try {
    el.setSelectionRange(end, end)
  } catch {
    /* 某些输入类型不支持 setSelectionRange；光标已在输入框内即可 */
  }
}

function setText(text: string): void {
  draft.value = text
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
    draft.value = next
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
  if (event.isComposing || !slashMatch.value || !slashItems.value.length) return
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
    event.preventDefault()
    event.stopPropagation()
    slashMatch.value = null
  }
}

/**
 * 旧 XSender 的 `submit-type="enter"`：回车发送、Shift+Enter 换行。
 * 斜杠菜单开着时把回车让给菜单（菜单在组件根上处理同一事件），避免既选技能又发送。
 */
function onInputKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Enter' || event.shiftKey) return
  // 中文输入法组字中的回车是在确认候选，不能当发送
  if (event.isComposing) return
  if (slashMatch.value && slashItems.value.length) return
  event.preventDefault()
  submit()
}

function onPaste(event: ClipboardEvent): void {
  const files = event.clipboardData?.files
  if (!files?.length) return
  void addImageFiles(files)
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
    toast.warning('请选择图片文件')
    return
  }
  const room = MAX_IMAGES - pendingImages.value.length
  if (room <= 0) {
    toast.warning(`最多 ${MAX_IMAGES} 张图`)
    return
  }
  const next = [...pendingImages.value]
  for (const file of list.slice(0, room)) {
    if (file.size > MAX_FILE_BYTES) {
      toast.warning(`${file.name} 过大（≤1.5MB）`)
      continue
    }
    try {
      const url = await fileToDataUrl(file)
      if (!url.startsWith('data:image/')) continue
      next.push(url)
    } catch {
      toast.warning(`${file.name} 读取失败`)
    }
  }
  pendingImages.value = next
}

async function onFileChange(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  if (input.files?.length) await addImageFiles(input.files)
  input.value = ''
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
    class="assistant-sender flex w-full min-w-0 flex-col"
    :class="{ 'is-generating': busy, 'is-locked': sessionLocked || !providerReady }"
    data-testid="assistant-sender"
    @keydown="onSlashKeydown"
  >
    <Command
      v-if="slashMatch && slashItems.length"
      class="assistant-sender__slash h-auto"
      data-testid="assistant-slash-menu"
      :model-value="slashItems[slashIndex]?.slug"
    >
      <CommandList :id="slashId" aria-label="技能">
        <CommandItem
          v-for="(item, index) in slashItems"
          :id="`${slashId}-${index}`"
          :key="item.slug"
          :value="item.slug"
          :text-value="`${item.slug} ${item.name} ${item.description}`"
          class="assistant-sender__slash-item"
          :class="{ 'is-active': index === slashIndex }"
          @mousedown.prevent
          @pointermove="slashIndex = index"
          @select="pickSkill(item)"
        >
          <span class="assistant-sender__slash-slug">/{{ item.slug }}</span>
          <span class="assistant-sender__slash-copy">
            <span>{{ item.name }}</span>
            <small v-if="item.description">{{ item.description }}</small>
          </span>
        </CommandItem>
      </CommandList>
    </Command>

    <InputGroup class="assistant-sender__box">
      <div v-if="activeSkill || pendingImages.length" class="assistant-sender__chips">
        <span v-if="activeSkill" class="assistant-sender__skill-chip" data-testid="assistant-active-skill">
          <Sparkles aria-hidden="true" />
          /{{ activeSkill.slug }} · {{ activeSkill.name }}
          <Button variant="ghost"
            type="button"
            class="assistant-sender__skill-close"
            :aria-label="`取消技能 /${activeSkill.slug}`"
            @click="clearActiveSkill"
          >
            <X aria-hidden="true" />
          </Button>
        </span>
        <AttachmentGroup v-if="pendingImages.length" class="assistant-sender__previews" data-testid="assistant-image-previews">
          <Attachment
            v-for="(src, index) in pendingImages"
            :key="`${index}-${src.slice(0, 32)}`"
            class="assistant-sender__preview"
            orientation="vertical"
            size="xs"
          >
            <AttachmentMedia variant="image" class="assistant-sender__preview-media"><img :src="src" alt="待发送图片" /></AttachmentMedia>
            <AttachmentActions class="assistant-sender__preview-actions"><AttachmentAction variant="ghost"
              type="button"
              class="assistant-sender__preview-remove"
              :aria-label="`移除第 ${index + 1} 张图片`"
              @click="removeImage(index)"
            >
              <X aria-hidden="true" />
            </AttachmentAction></AttachmentActions>
          </Attachment>
        </AttachmentGroup>
      </div>
      <Textarea
        data-slot="input-group-control" ref="inputRef"
        v-model="draft"
        class="assistant-sender__input"
        :placeholder="placeholder"
        aria-label="消息内容"
        :aria-controls="slashMatch && slashItems.length ? slashId : undefined"
        :aria-expanded="Boolean(slashMatch && slashItems.length)"
        :aria-activedescendant="slashMatch && slashItems.length ? `${slashId}-${slashIndex}` : undefined"
        aria-autocomplete="list"
        :disabled="busy || !providerReady"
        :maxlength="MAX_TEXT_LENGTH"
        :rows="1"
        @input="syncEmpty"
        @keydown="onInputKeydown"
        @paste="onPaste"
      />
      <InputGroupAddon align="block-end" class="assistant-sender__bar">
        <div class="assistant-sender__bar-left">
          <Tooltip>
            <TooltipTrigger as-child>
              <Button
                variant="ghost"
                size="icon-sm"
                class="assistant-sender__attach"
                :disabled="busy || !providerReady || pendingImages.length >= MAX_IMAGES"
                aria-label="上传图片"
                data-testid="assistant-attach-image"
                @click="openFilePicker"
              >
                <ImagePlus />
              </Button>
            </TooltipTrigger>
            <TooltipContent>上传图片（≤4 张）</TooltipContent>
          </Tooltip>
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
          <Tooltip v-if="busy || waitingUser">
            <TooltipTrigger as-child>
              <Button
                variant="outline"
                size="icon-sm"
                class="assistant-sender__stop"
                :aria-label="waitingUser ? '取消等待' : '中止运行'"
                @click="emit('cancel')"
              >
                <Square class="size-3.5 fill-current" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{{ waitingUser ? '取消等待并中止' : '中止运行' }}</TooltipContent>
          </Tooltip>
          <Tooltip v-if="!busy">
            <TooltipTrigger as-child>
              <Button
                size="icon-sm"
                class="assistant-sender__send"
                :disabled="!canSend"
                :aria-label="waitingUser ? '回复并继续' : '发送消息'"
                @click="submit"
              >
                <ArrowUp />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{{ waitingUser ? '回复并继续' : '发送 · Shift+Enter 换行' }}</TooltipContent>
          </Tooltip>
        </div>
      </InputGroupAddon>
    </InputGroup>
  </div>
</template>

<style scoped src="./AssistantSenderDock.css"></style>
