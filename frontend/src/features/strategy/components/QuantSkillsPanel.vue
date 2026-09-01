<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { RefreshRight, Search } from '@element-plus/icons-vue'

import { installSkill, syncSkillTemplates } from '@/shared/api/quant'
import PageContainer from '@/shared/components/layout/PageContainer.vue'
import BasicForm, { type BasicFormSchema } from '@/shared/components/ui/BasicForm.vue'
import { formValuesEqual } from '@/shared/components/ui/basicFormEqual'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import RowActions from '@/shared/components/ui/RowActions.vue'
import { toErrorMessage } from '@/shared/lib/errors'
import { zipFolderFiles } from '@/shared/lib/zipStore'
import { strategyLabel } from '@/shared/lib/format'
import type { Skill } from '@/shared/types/quant'

import SkillDetailDialog from './SkillDetailDialog.vue'

const props = defineProps<{
  skills: Skill[]
  loading?: boolean
}>()

const emit = defineEmits<{
  openScreen: [slug: string]
  remove: [skill: Skill]
  refresh: []
}>()

const route = useRoute()
const router = useRouter()
const basicFormRef = ref<InstanceType<typeof BasicForm>>()
const zipInput = ref<HTMLInputElement | null>(null)
const folderInput = ref<HTMLInputElement | null>(null)
const installing = ref(false)
const nameQuery = ref('')
const detailOpen = ref(false)
const detail = ref<Skill | null>(null)

watch(
  () => [props.skills, route.query.skill] as const,
  ([list, raw]) => {
    const slug = String(raw || '').trim()
    if (!slug || !list.length) return
    const hit = list.find((s) => s.slug === slug)
    if (!hit) return
    detail.value = hit
    detailOpen.value = true
    const nextQuery = { ...route.query }
    delete nextQuery.skill
    void router.replace({ query: nextQuery })
  },
  { immediate: true },
)

const filters = reactive({
  name: '',
})

const filterModel = computed({
  get: () => filters as Record<string, unknown>,
  set: (value: Record<string, unknown>) => {
    const next = String(value.name ?? '')
    if (!formValuesEqual(filters.name, next)) filters.name = next
  },
})

const filterSchemas: BasicFormSchema[] = [
  {
    field: 'name',
    label: '名称',
    component: 'input',
    colSpan: 8,
    componentProps: {
      clearable: true,
      placeholder: '模糊查询技能名',
      maxlength: 64,
    },
  },
]

/**
 * 名称列一律中文：后端 `name` 缺失、或它本身就是 slug 形状时退回共享词表。
 * 搜索仍然吃 slug，那是标识不是展示。
 */
function displayName(name: unknown, slug: unknown): string {
  const text = String(name || '').trim()
  if (text && !/^[a-z0-9][a-z0-9._-]*$/.test(text)) return text
  return strategyLabel(String(slug || '') || text)
}

const filteredRows = computed(() => {
  const q = nameQuery.value.trim().toLowerCase()
  const list = !q
    ? props.skills
    : props.skills.filter(
        (row) =>
          row.name.toLowerCase().includes(q)
          || row.slug.toLowerCase().includes(q)
          || row.description.toLowerCase().includes(q),
      )
  return list as unknown as Record<string, unknown>[]
})

const columns = ref<BasicTableColumn[]>([
  {
    prop: 'name',
    label: '名称',
    minWidth: 180,
    slotName: 'name',
  },
  {
    prop: 'version',
    label: '版本',
    width: 88,
    formatter: (row) => String(row.version || '—'),
  },
  {
    prop: 'enabled',
    label: '状态',
    width: 88,
    slotName: 'enabled',
  },
  {
    prop: 'allowed_tools',
    label: '工具',
    minWidth: 160,
    slotName: 'tools',
  },
  {
    prop: 'description',
    label: '说明',
    minWidth: 180,
    align: 'left',
    headerAlign: 'left',
    showOverflowTooltip: true,
    formatter: (row) => String(row.description || '—'),
  },
  {
    prop: 'actions',
    label: '操作',
    align: 'center',
    headerAlign: 'center',
    width: 132,
    fixed: 'right',
    slotName: 'actions',
  },
])

function handleSubmit(): void {
  nameQuery.value = filters.name
}

function handleReset(): void {
  basicFormRef.value?.resetForm()
  filters.name = ''
  nameQuery.value = ''
}

function onRowClick(row: Record<string, unknown>): void {
  detail.value = row as unknown as Skill
  detailOpen.value = true
}

function toolLabels(row: Record<string, unknown>): string[] {
  const tools = row.allowed_tools
  return Array.isArray(tools) ? tools.map((item) => String(item)) : []
}

function pickZip(): void {
  zipInput.value?.click()
}

function pickFolder(): void {
  folderInput.value?.click()
}

function onUploadCommand(command: string | number | object): void {
  if (command === 'folder') pickFolder()
  else pickZip()
}

async function syncFromTemplates(): Promise<void> {
  installing.value = true
  try {
    const result = await syncSkillTemplates(true)
    const parts: string[] = []
    if (result.installed.length) parts.push(`已安装 ${result.installed.length} 个`)
    if (result.skipped.length) parts.push(`跳过 ${result.skipped.length} 个`)
    if (result.errors.length) parts.push(`失败 ${result.errors.length} 个`)
    if (result.errors.length) {
      ElMessage.warning(parts.join('，') || '同步完成')
    } else {
      ElMessage.success(parts.join('，') || '模板目录为空，无需同步')
    }
    if (result.installed.length) emit('refresh')
  } catch (caught: unknown) {
    ElMessage.error(toErrorMessage(caught, '模板同步失败'))
  } finally {
    installing.value = false
  }
}

async function installPackage(file: File): Promise<void> {
  installing.value = true
  try {
    const installed = await installSkill(file)
    ElMessage.success(`已安装「${installed.name}」`)
    emit('refresh')
  } catch (caught: unknown) {
    ElMessage.error(toErrorMessage(caught, '安装失败'))
  } finally {
    installing.value = false
  }
}

async function onZipSelected(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  await installPackage(file)
}

async function onFolderSelected(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const files = input.files
  input.value = ''
  if (!files?.length) return
  installing.value = true
  try {
    const zip = await zipFolderFiles(files)
    const installed = await installSkill(zip)
    ElMessage.success(`已安装「${installed.name}」`)
    emit('refresh')
  } catch (caught: unknown) {
    ElMessage.error(toErrorMessage(caught, '安装失败'))
  } finally {
    installing.value = false
  }
}
</script>

<template>
  <div class="skills-panel">
    <!-- 原生 file：选 zip / 选文件夹（webkitdirectory）；由「上传技能」触发 -->
    <input
      ref="zipInput"
      type="file"
      accept=".zip,application/zip"
      hidden
      @change="onZipSelected"
    />
    <input
      ref="folderInput"
      type="file"
      webkitdirectory
      multiple
      hidden
      @change="onFolderSelected"
    />
    <PageContainer>
      <template #search>
        <div class="skills-search-form">
          <BasicForm
            ref="basicFormRef"
            v-model="filterModel"
            :schemas="filterSchemas"
            :col-props="{ span: 8 }"
            :input-debounce-ms="0"
            label-width="6.5em"
          />
        </div>
        <div class="skills-search-actions">
          <el-button type="primary" :icon="Search" @click="handleSubmit">查询</el-button>
          <el-button :icon="RefreshRight" @click="handleReset">重置</el-button>
        </div>
      </template>
      <template #main>
        <BasicTable
          v-if="filteredRows.length || loading"
          v-model:columns="columns"
          :data-source="filteredRows"
          :pagination="false"
          :loading="loading || installing"
          :toolbar-config="{ refresh: true }"
          stripe
          row-key="slug"
          empty-text="无匹配技能"
          @row-click="onRowClick"
          @refresh="emit('refresh')"
        >
          <template #toolbarButtons>
            <el-button
              size="small"
              :disabled="installing"
              @click="syncFromTemplates"
            >
              从模板同步战法
            </el-button>
            <el-dropdown
              split-button
              type="primary"
              size="small"
              :disabled="installing"
              @click="pickZip"
              @command="onUploadCommand"
            >
              上传技能
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="zip">选择 zip</el-dropdown-item>
                  <el-dropdown-item command="folder">选择文件夹</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
          <template #name="{ row }">
            <strong>{{ displayName(row.name, row.slug) }}</strong>
          </template>
          <template #enabled="{ row }">
            <el-tag
              size="small"
              :type="row.enabled === false ? 'info' : 'success'"
              effect="plain"
            >
              {{ row.enabled === false ? '停用' : '启用' }}
            </el-tag>
          </template>
          <template #tools="{ row }">
            <el-tag
              v-for="tool in toolLabels(row).slice(0, 3)"
              :key="tool"
              size="small"
              effect="plain"
              class="tool-tag"
            >
              {{ tool }}
            </el-tag>
            <span v-if="toolLabels(row).length > 3" class="more">
              +{{ toolLabels(row).length - 3 }}
            </span>
            <span v-if="!toolLabels(row).length" class="dim">—</span>
          </template>
          <template #actions="{ row }">
            <RowActions
              :max-visible="2"
              :actions="[
                {
                  key: 'open',
                  label: '去选股',
                  onClick: () => emit('openScreen', String(row.slug)),
                },
                {
                  key: 'remove',
                  label: '卸载',
                  type: 'danger',
                  onClick: () => emit('remove', row as unknown as Skill),
                },
              ]"
            />
          </template>
        </BasicTable>
        <EmptyState
          v-else
          description="还没有技能"
          reason="本机安装技能包后会出现在这里"
          eta="点「从模板同步战法」或「上传技能」"
        >
          <el-button
            type="primary"
            plain
            :disabled="installing"
            @click="syncFromTemplates"
          >
            从模板同步战法
          </el-button>
          <el-dropdown
            split-button
            type="primary"
            :disabled="installing"
            @click="pickZip"
            @command="onUploadCommand"
          >
            上传技能
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="zip">选择 zip</el-dropdown-item>
                <el-dropdown-item command="folder">选择文件夹</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </EmptyState>
      </template>
    </PageContainer>

    <SkillDetailDialog
      v-model="detailOpen"
      :skill="detail"
      @open-screen="(slug) => emit('openScreen', slug)"
      @remove="(skill) => emit('remove', skill)"
    />
  </div>
</template>

<style scoped>
.skills-panel {
  flex: 1 1 auto;
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.skills-search-form {
  flex: 1;
  min-width: 0;
}

.skills-search-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  flex-shrink: 0;
  padding-bottom: 0.65rem;
}

.tool-tag {
  margin: 0 0.25rem 0.2rem 0;
}

.more,
.dim {
  color: var(--mist);
  font-size: 0.78rem;
}

:deep(.el-dropdown) {
  vertical-align: middle;
}
</style>
