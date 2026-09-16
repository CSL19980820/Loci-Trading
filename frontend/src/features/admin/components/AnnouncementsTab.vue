<script setup lang="ts">
import { RefreshRight } from '@element-plus/icons-vue'
/**
 * 全站公告。列表页骨架（筛选 + BasicTable + RowActions），不再自绘卡片流。
 *
 * 旧版是一列卡片，每张卡把 Markdown 全文渲染出来，还靠一条 4px 的左侧色条标级别：
 * 三条公告就能拉出两屏，那条色条又正是全站要清掉的装饰线。级别现在是一枚中文
 * el-tag，正文沉到「预览正文」弹窗——列表页的职责是「找到那条公告」，不是读全文。
 *
 * **为什么是前端分页**：`GET /admin/announcements` 既不吃分页参数也不吃筛选参数，
 * 一次就返回全量；而公告总量是十量级（运营手写、过期即删），一次拉全、在
 * `computed` 里筛、在本地切页最省事，也不必为此给后端加参数。真到了千量级再改后端，
 * 那时这里换成 `:request` 即可，列定义不用动。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { deleteAdminAnnouncement, listAdminAnnouncements } from '@/shared/api/admin'
import PageContainer from '@/shared/components/layout/PageContainer.vue'
import BasicForm from '@/shared/components/ui/BasicForm.vue'
import type { BasicFormSchema } from '@/shared/components/ui/basicFormTypes'
import BasicTable from '@/shared/components/ui/BasicTable.vue'
import type { BasicTableColumn } from '@/shared/components/ui/basicTableTypes'
import ListToolbar from '@/shared/components/ui/ListToolbar.vue'
import type { ListToolbarConfig } from '@/shared/components/ui/ListToolbar.vue'
import RowActions from '@/shared/components/ui/RowActions.vue'
import type { RowAction } from '@/shared/components/ui/RowActions.vue'
import { confirmDangerous } from '@/shared/lib/confirm'
import { toErrorMessage } from '@/shared/lib/errors'
import type { AdminAnnouncementItem } from '@/shared/types/admin'
import { LEVEL_OPTIONS, accountTime, levelLabel, levelTagType } from '../lib/adminDict'
import { renderAnnouncementMarkdown } from '../lib/adminFormat'
import AnnouncementEditorDialog from './AnnouncementEditorDialog.vue'

const PAGE_SIZE = 20

const loading = ref(false)
const announcements = ref<AdminAnnouncementItem[]>([])
const filters = ref<Record<string, unknown>>({ keyword: '', level: '' })
const page = ref(1)

const editorVisible = ref(false)
const selectedItem = ref<AdminAnnouncementItem | null>(null)

const previewVisible = ref(false)
const previewItem = ref<AdminAnnouncementItem | null>(null)

const filterSchemas: BasicFormSchema[] = [
  {
    field: 'keyword',
    label: '关键词',
    componentProps: { placeholder: '标题 / 正文', clearable: true },
  },
  {
    field: 'level',
    label: '级别',
    component: 'select',
    componentProps: { placeholder: '全部', clearable: true, options: [...LEVEL_OPTIONS] },
  },
]

const columns = ref<BasicTableColumn[]>([
  {
    prop: 'level',
    label: '级别',
    width: 88,
    align: 'center',
    headerAlign: 'center',
    slotName: 'level',
  },
  { prop: 'title', label: '标题', minWidth: 200, showOverflowTooltip: true },
  {
    prop: 'created_by',
    label: '发布人',
    width: 120,
    showOverflowTooltip: true,
    formatter: (row) => (row.created_by as string) || '—',
  },
  {
    prop: 'published_at',
    label: '发布时间',
    width: 150,
    align: 'center',
    headerAlign: 'center',
    formatter: (row) => accountTime((row.published_at as string) || (row.created_at as string)),
  },
  {
    prop: 'expires_at',
    label: '过期时间',
    width: 150,
    align: 'center',
    headerAlign: 'center',
    formatter: (row) => accountTime(row.expires_at as string, '不过期'),
  },
  {
    prop: 'actions',
    label: '操作',
    width: 128,
    fixed: 'right',
    align: 'center',
    headerAlign: 'center',
    slotName: 'actions',
  },
])

const filtered = computed(() => {
  const keyword = String(filters.value.keyword || '')
    .trim()
    .toLowerCase()
  const level = String(filters.value.level || '')
  return announcements.value.filter((item) => {
    if (level && (item.level || 'info') !== level) return false
    if (!keyword) return true
    const haystack = `${item.title || ''}\n${item.body_md || ''}`.toLowerCase()
    return haystack.includes(keyword)
  })
})

const pagedRows = computed(() => {
  const start = (page.value - 1) * PAGE_SIZE
  return filtered.value.slice(start, start + PAGE_SIZE) as unknown as Record<string, unknown>[]
})

const pager = computed(() => ({
  pageSize: PAGE_SIZE,
  currentPage: page.value,
  total: filtered.value.length,
  layout: 'total, prev, pager, next',
}))

const previewHtml = computed(() =>
  previewItem.value ? renderAnnouncementMarkdown(previewItem.value.body_md) : '',
)

const toolbarConfig = computed<ListToolbarConfig>(() => ({
  create: { onClick: openCreateDialog },
}))

watch(filters, () => {
  page.value = 1
})

// 删完最后一页的最后一条时，别把用户留在一张空页上
watch(filtered, () => {
  const lastPage = Math.max(1, Math.ceil(filtered.value.length / PAGE_SIZE) || 1)
  if (page.value > lastPage) page.value = lastPage
})

async function loadAnnouncements(): Promise<void> {
  loading.value = true
  try {
    const res = await listAdminAnnouncements()
    announcements.value = res.items
  } catch (caught: unknown) {
    ElMessage.error(toErrorMessage(caught, '加载公告列表失败'))
  } finally {
    loading.value = false
  }
}

function onReset(): void {
  filters.value = { keyword: '', level: '' }
  page.value = 1
}

function openCreateDialog(): void {
  selectedItem.value = null
  editorVisible.value = true
}

function openEditDialog(item: AdminAnnouncementItem): void {
  selectedItem.value = item
  editorVisible.value = true
}

function openPreview(item: AdminAnnouncementItem): void {
  previewItem.value = item
  previewVisible.value = true
}

async function handleDelete(item: AdminAnnouncementItem): Promise<void> {
  const confirmed = await confirmDangerous(
    `确定要删除公告「${item.title}」吗？删除后全站用户将无法再看到该公告。`,
    '删除公告确认',
    '确认删除',
  )
  if (!confirmed) return

  try {
    await deleteAdminAnnouncement(item.id)
    ElMessage.success('公告已删除')
    void loadAnnouncements()
  } catch (caught: unknown) {
    ElMessage.error(toErrorMessage(caught, '删除公告失败'))
  }
}

function rowActions(item: AdminAnnouncementItem): RowAction[] {
  return [
    { key: 'edit', label: '编辑', onClick: () => openEditDialog(item) },
    { key: 'preview', label: '预览正文', onClick: () => openPreview(item) },
    {
      key: 'delete',
      label: '删除',
      type: 'danger',
      divided: true,
      onClick: () => void handleDelete(item),
    },
  ]
}

onMounted(() => {
  void loadAnnouncements()
})
</script>

<template>
  <div class="admin-pane admin-list">
    <PageContainer>
      <template #search>
        <div class="admin-pane__filters">
          <BasicForm
            v-model="filters"
            :schemas="filterSchemas"
            :columns="2"
            label-position="left"
            label-width="4.5em"
          />
        </div>
        <div class="admin-pane__filter-actions">
          <el-button :icon="RefreshRight" @click="onReset">重置</el-button>
        </div>
      </template>

      <template #main>
        <BasicTable
          v-model:columns="columns"
          :data-source="pagedRows"
          :pagination="pager"
          :loading="loading"
          :toolbar-config="{ refresh: true }"
          height="100%"
          row-key="id"
          stripe
          empty-text="还没有全站公告"
          @current-change="(next: number) => (page = next)"
          @refresh="loadAnnouncements"
        >
          <template #toolbarButtons>
            <ListToolbar :config="toolbarConfig" />
          </template>

          <template #level="{ row }">
            <el-tag :type="levelTagType(row.level as string)" size="small" effect="plain">
              {{ levelLabel(row.level as string) }}
            </el-tag>
          </template>

          <template #actions="{ row }">
            <RowActions
              :actions="rowActions(row as unknown as AdminAnnouncementItem)"
              :max-visible="1"
            />
          </template>
        </BasicTable>
      </template>
    </PageContainer>

    <!-- 正文预览：列表页只认标题与时间，全文在这里读 -->
    <el-dialog
      v-model="previewVisible"
      :title="previewItem?.title || '公告正文'"
      width="min(92vw, 560px)"
      class="announcement-preview dialog-body--scroll"
    >
      <div v-if="previewHtml" class="announcement-preview__body" v-html="previewHtml" />
      <p v-else class="announcement-preview__empty">这条公告没有正文</p>
    </el-dialog>

    <AnnouncementEditorDialog
      v-model:visible="editorVisible"
      :item="selectedItem"
      @saved="loadAnnouncements"
    />
  </div>
</template>

<style scoped>
.announcement-preview__empty {
  margin: 0;
  color: var(--mist);
  font-size: var(--fs-body);
}
</style>

<style scoped src="./AnnouncementPreview.css" />

<style scoped src="./AdminList.css" />
