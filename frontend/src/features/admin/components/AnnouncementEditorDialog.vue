<script setup lang="ts">
/**
 * 公告编辑弹窗。
 *
 * 本轮只改两处，Markdown 预览保持原样（同一个 `renderAnnouncementMarkdown`，
 * 同一个「编辑 / 预览」切换）：
 * 1. **级别选项统一走 `LEVEL_OPTIONS`**（通知 / 警告 / 严重），单选按钮上不再挂英文
 *    机器码括注——枚举文案的唯一真相在 `lib/adminDict.ts`。
 * 2. **裸 `el-form` 换成 `BasicForm`**（全站表单契约）：label 宽度、行距、
 *    hint / tooltip 的落点都由契约保证，不再在本文件自拼 label 行。
 *    「编辑 / 预览」也是一个 schema 字段（`view`），正文与预览靠 `hidden` 互斥，
 *    这样切换控件跟着表单栅格排，不用在 form-item 里塞一个自绘的右对齐工具条。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { upsertAdminAnnouncement } from '@/shared/api/admin'
import BasicForm from '@/shared/components/ui/BasicForm.vue'
import type { BasicFormSchema } from '@/shared/components/ui/basicFormTypes'
import { toErrorMessage } from '@/shared/lib/errors'
import type { AdminAnnouncementItem, UpsertAnnouncementPayload } from '@/shared/types/admin'
import { LEVEL_OPTIONS } from '../lib/adminDict'
import { renderAnnouncementMarkdown } from '../lib/adminFormat'

type AnnouncementLevel = AdminAnnouncementItem['level']

const props = defineProps<{
  visible: boolean
  item: AdminAnnouncementItem | null
}>()

const emit = defineEmits<{
  (e: 'update:visible', val: boolean): void
  (e: 'saved'): void
}>()

const VIEW_OPTIONS = [
  { label: '编辑', value: 'edit' },
  { label: '预览', value: 'preview' },
]

function emptyForm(): Record<string, unknown> {
  return {
    id: '',
    title: '',
    level: 'info',
    published_at: '',
    expires_at: '',
    view: 'edit',
    body_md: '',
  }
}

const formRef = ref<InstanceType<typeof BasicForm>>()
const form = ref<Record<string, unknown>>(emptyForm())
const loading = ref(false)

const previewMode = computed(() => form.value.view === 'preview')
const renderedBody = computed(() => renderAnnouncementMarkdown(String(form.value.body_md || '')))

const schemas = computed<BasicFormSchema[]>(() => [
  {
    field: 'title',
    label: '标题',
    fullRow: true,
    componentProps: {
      placeholder: '如：平台系统升级维护通知',
      maxlength: 120,
      showWordLimit: true,
    },
    rules: [{ required: true, message: '填公告标题', trigger: 'change' }],
  },
  {
    field: 'level',
    label: '级别',
    component: 'RadioGroup',
    componentProps: { options: [...LEVEL_OPTIONS] },
  },
  {
    field: 'published_at',
    label: '发布时间',
    hint: '留空即当前时间，格式 2026-08-27T00:00:00Z',
    componentProps: { placeholder: '留空即当前时间' },
  },
  {
    field: 'expires_at',
    label: '过期时间',
    hint: '留空即永久有效，格式 2026-09-01T00:00:00Z',
    componentProps: { placeholder: '留空即永久有效' },
  },
  {
    field: 'view',
    label: '正文视图',
    component: 'RadioGroup',
    componentProps: { options: VIEW_OPTIONS },
  },
  {
    field: 'body_md',
    label: '正文内容',
    fullRow: true,
    hidden: previewMode.value,
    componentProps: {
      type: 'textarea',
      rows: 8,
      placeholder: '支持完整 Markdown 语法',
      maxlength: 8000,
      showWordLimit: true,
    },
  },
  {
    field: 'preview',
    label: '正文预览',
    fullRow: true,
    hidden: !previewMode.value,
    slotName: 'preview',
  },
])

/**
 * 表单回填。除了 `item` 变化，**每次打开也回填一次**：连开两次「新增」时
 * `item` 都是 null、watch 不会触发，上一次没提交的草稿会留在第二张空表里。
 */
function syncForm(): void {
  const next = emptyForm()
  const val = props.item
  if (val) {
    next.id = val.id
    next.title = val.title
    next.level = val.level || 'info'
    next.published_at = val.published_at || ''
    next.expires_at = val.expires_at || ''
    next.body_md = val.body_md
  }
  form.value = next
}

watch(() => props.item, syncForm, { immediate: true })

watch(
  () => props.visible,
  (open) => {
    if (open) syncForm()
  },
)

function onClose(): void {
  emit('update:visible', false)
}

async function onSubmit(): Promise<void> {
  const values = await formRef.value?.submit()
  if (!values) return

  loading.value = true
  try {
    const id = String(values.id || '')
    const payload: UpsertAnnouncementPayload = {
      id: id || undefined,
      title: String(values.title || '').trim(),
      body_md: String(values.body_md || '').trim(),
      level: (values.level as AnnouncementLevel) || 'info',
      published_at: String(values.published_at || '') || null,
      expires_at: String(values.expires_at || '') || null,
    }
    await upsertAdminAnnouncement(payload)
    ElMessage.success(id ? '公告已更新' : '公告已发布')
    emit('saved')
    onClose()
  } catch (caught: unknown) {
    ElMessage.error(toErrorMessage(caught, '保存公告失败'))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    :title="item ? '编辑公告' : '新建全站公告'"
    width="min(92vw, 680px)"
    @close="onClose"
  >
    <BasicForm ref="formRef" v-model="form" :schemas="schemas" :columns="2" :input-debounce-ms="0">
      <template #preview>
        <div
          class="md-preview-pane"
          v-html="renderedBody || '<span class=\'placeholder-text\'>暂无内容</span>'"
        />
      </template>
    </BasicForm>

    <template #footer>
      <div class="dialog-footer">
        <el-button @click="onClose">取消</el-button>
        <el-button type="primary" :loading="loading" @click="onSubmit">保存并发布</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.md-preview-pane {
  width: 100%;
  /* 无下限：空预览就该只有一行高，不用 180px 撑一块死白 */
  max-height: 20rem;
  overflow-y: auto;
  padding: var(--gap-2);
  background: var(--sheet);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  font-size: var(--fs-body);
  line-height: 1.6;
}

.placeholder-text {
  color: var(--mist);
}
</style>
