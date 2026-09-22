<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { toast } from 'vue-sonner'
import { ChevronDown, Cpu, Ellipsis, Info, Play, RefreshCw, Search, Trash2, Upload, X } from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'

import { installSkill, syncSkillTemplates } from '@/shared/api/quant'
import { Button } from '@/shared/components/ui/button'
import { Card } from '@/shared/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/shared/components/ui/dropdown-menu'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { Input } from '@/shared/components/ui/input'
import { Skeleton } from '@/shared/components/ui/skeleton'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
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
const zipInput = ref<HTMLInputElement | null>(null)
const folderInput = ref<HTMLInputElement | null>(null)
const installing = ref(false)
const query = ref('')
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

/**
 * 名称一律中文：后端 `name` 缺失、或它本身就是 slug 形状时退回共享词表。
 * 搜索仍然吃 slug，那是标识不是展示。
 */
function displayName(name: unknown, slug: unknown): string {
  const text = String(name || '').trim()
  if (text && !/^[a-z0-9][a-z0-9._-]*$/.test(text)) return text
  return strategyLabel(String(slug || '') || text)
}

/** 运行时徽标：隔离等级 + 权限策略（技能包 metadata 里声明的口径） */
function isolationLabel(value: string | undefined): string {
  if (!value) return ''
  if (value === 'sandbox') return '沙箱'
  if (value === 'strict') return '严格隔离'
  if (value === 'none') return '无隔离'
  return value
}

function policyLabel(value: string | undefined): string {
  if (!value) return ''
  if (value === 'read_only') return '只读'
  if (value === 'trade') return '可交易'
  return value
}

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return props.skills
  return props.skills.filter(
    (row) =>
      row.name.toLowerCase().includes(q)
      || row.slug.toLowerCase().includes(q)
      || row.description.toLowerCase().includes(q),
  )
})

function openDetail(skill: Skill): void {
  detail.value = skill
  detailOpen.value = true
}

function toolLabels(row: Skill): string[] {
  return Array.isArray(row.allowed_tools) ? row.allowed_tools.map((item) => String(item)) : []
}

function pickZip(): void {
  zipInput.value?.click()
}

function pickFolder(): void {
  folderInput.value?.click()
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
      toast.warning(parts.join('，') || '同步完成')
    } else {
      toast.success(parts.join('，') || '模板目录为空，无需同步')
    }
    if (result.installed.length) emit('refresh')
  } catch (caught: unknown) {
    toast.error(toErrorMessage(caught, '模板同步失败'))
  } finally {
    installing.value = false
  }
}

async function installPackage(file: File): Promise<void> {
  installing.value = true
  try {
    const installed = await installSkill(file)
    toast.success(`已安装「${installed.name}」`)
    emit('refresh')
  } catch (caught: unknown) {
    toast.error(toErrorMessage(caught, '安装失败'))
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
    toast.success(`已安装「${installed.name}」`)
    emit('refresh')
  } catch (caught: unknown) {
    toast.error(toErrorMessage(caught, '安装失败'))
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

    <div class="skills-toolbar">
      <div class="skills-search">
        <Search class="skills-search__icon" aria-hidden="true" />
        <Input
          v-model="query"
          size="sm"
          class="skills-search__input"
          placeholder="搜索技能名、slug 或说明"
          aria-label="搜索技能"
          maxlength="64"
        />
        <Button access="read" v-if="query" variant="ghost" size="icon-xs" class="skills-search__clear" aria-label="清空搜索" @click="query = ''">
          <X aria-hidden="true" />
        </Button>
      </div>
      <div class="skills-toolbar__actions">
        <Button access="read" size="sm" variant="ghost" :disabled="loading || installing" aria-label="刷新技能列表" @click="emit('refresh')">
          <RefreshCw :class="{ 'animate-spin motion-reduce:animate-none': loading }" aria-hidden="true" />
          刷新
        </Button>
        <Button size="sm" variant="outline" :disabled="installing" @click="syncFromTemplates">
          从模板同步
        </Button>
        <div class="upload-split">
          <Button size="sm" class="upload-split__main" :disabled="installing" @click="pickZip">
            <Upload aria-hidden="true" />
            上传技能
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger as-child>
              <Button size="sm" class="upload-split__caret" :disabled="installing" aria-label="更多上传方式">
                <ChevronDown aria-hidden="true" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem @select="pickZip">选择 zip</DropdownMenuItem>
              <DropdownMenuItem @select="pickFolder">选择文件夹</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </div>

    <div class="skills-scroll">
      <div v-if="(loading || installing) && !skills.length" class="skills-grid" aria-hidden="true">
        <Skeleton v-for="n in 3" :key="n" class="h-[196px] rounded-lg" />
      </div>

      <EmptyState
        v-else-if="!filtered.length"
        :icon="Cpu"
        :description="query ? '当前筛选下无结果' : '还没有技能'"
        :reason="query ? '换个关键字，或清空搜索' : '上传技能包，或从模板目录同步内置技能'"
        class="skills-empty"
      >
        <Button access="read" v-if="query" variant="outline" size="sm" @click="query = ''">清空搜索</Button>
        <template v-else>
          <Button size="sm" :disabled="installing" @click="pickZip">
            <Upload aria-hidden="true" />
            上传技能
          </Button>
          <Button variant="outline" size="sm" :disabled="installing" @click="syncFromTemplates">从模板同步</Button>
        </template>
      </EmptyState>

      <ul v-else class="skills-grid" :aria-busy="installing">
        <li v-for="row in filtered" :key="row.slug">
          <Card
            interactive
            class="skill-card"
            :class="{ 'is-disabled': row.enabled === false }"
            role="button"
            tabindex="0"
            :aria-label="`查看${displayName(row.name, row.slug)}详情`"
            @click="openDetail(row)"
            @keydown.enter.prevent="openDetail(row)"
          >
            <header class="skill-card__head">
              <span class="skill-card__avatar" aria-hidden="true"><Cpu /></span>
              <div class="skill-card__identity">
                <strong class="skill-card__name">{{ displayName(row.name, row.slug) }}</strong>
                <span class="skill-card__slug">{{ row.slug }}<template v-if="row.version"> · v{{ row.version }}</template></span>
              </div>
              <UiBadge :variant="row.enabled === false ? 'secondary' : 'ok'" dot class="skill-card__status">
                {{ row.enabled === false ? '停用' : '启用' }}
              </UiBadge>
            </header>

            <p class="skill-card__desc">{{ row.description || '这个技能没有说明。' }}</p>

            <div class="skill-card__runtime">
              <UiBadge v-if="isolationLabel(row.isolation)" variant="info">{{ isolationLabel(row.isolation) }}</UiBadge>
              <UiBadge v-if="policyLabel(row.policy)" variant="outline">{{ policyLabel(row.policy) }}</UiBadge>
              <UiBadge v-if="row.mcp_servers?.length" variant="outline">MCP × {{ row.mcp_servers.length }}</UiBadge>
              <span v-if="toolLabels(row).length" class="skill-card__tools">
                <span v-for="tool in toolLabels(row).slice(0, 3)" :key="tool" class="skill-card__tool">{{ tool }}</span>
                <span v-if="toolLabels(row).length > 3" class="skill-card__tool skill-card__tool--more">+{{ toolLabels(row).length - 3 }}</span>
              </span>
              <span v-else class="skill-card__tools skill-card__tools--none">未声明工具</span>
            </div>

            <footer class="skill-card__foot" @click.stop>
              <Button access="read" size="xs" variant="outline" :disabled="row.enabled === false" @click="emit('openScreen', row.slug)">
                <Play aria-hidden="true" />
                去选股
              </Button>
              <Button access="read" size="xs" variant="ghost" @click="openDetail(row)">
                <Info aria-hidden="true" />
                详情
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger as-child>
                  <Button size="icon-xs" variant="ghost" class="ml-auto" :aria-label="`${displayName(row.name, row.slug)} 更多操作`">
                    <Ellipsis aria-hidden="true" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem access="read" @select="openDetail(row)">
                    <Info aria-hidden="true" />
                    查看详情
                  </DropdownMenuItem>
                  <DropdownMenuItem access="read" :disabled="row.enabled === false" @select="emit('openScreen', row.slug)">
                    <Play aria-hidden="true" />
                    去选股
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem variant="destructive" @select="emit('remove', row)">
                    <Trash2 aria-hidden="true" />
                    卸载技能
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </footer>
          </Card>
        </li>
      </ul>
    </div>

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
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: var(--gap-3);
  min-height: 0;
  height: 100%;
}

.skills-toolbar {
  display: flex;
  flex-shrink: 0;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-2) var(--gap-3);
}

.skills-search {
  position: relative;
  display: flex;
  flex: 0 1 320px;
  align-items: center;
  min-width: 200px;
}

.skills-search__icon {
  position: absolute;
  left: 9px;
  width: 14px;
  height: 14px;
  color: var(--text-tertiary);
  pointer-events: none;
}

.skills-search__input {
  padding-left: 28px;
  padding-right: 28px;
}

.skills-search__clear {
  position: absolute;
  right: 3px;
}

.skills-toolbar__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2);
}

.upload-split {
  display: inline-flex;
  align-items: center;
}

.upload-split__main {
  border-top-right-radius: 0;
  border-bottom-right-radius: 0;
}

.upload-split__caret {
  padding-inline: var(--gap-1);
  border-top-left-radius: 0;
  border-bottom-left-radius: 0;
  box-shadow: none;
  border-left: 1px solid color-mix(in oklab, var(--on-primary, #fff) 25%, transparent);
}

.skills-scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  padding-bottom: var(--gap-4);
}

.skills-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: var(--gap-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.skills-empty {
  min-height: 260px;
  border: 1px dashed var(--border-default);
  border-radius: var(--radius-lg);
  background: var(--surface);
}

.skill-card {
  gap: var(--gap-3);
  height: 100%;
  padding: var(--gap-4);
}

.skill-card:focus-visible {
  outline: 2px solid var(--focus-ring, var(--seal));
  outline-offset: 2px;
}

.skill-card.is-disabled {
  background: color-mix(in oklab, var(--surface) 70%, var(--surface-canvas));
}

.skill-card.is-disabled .skill-card__name,
.skill-card.is-disabled .skill-card__desc {
  color: var(--text-secondary);
}

.skill-card__head {
  display: flex;
  align-items: flex-start;
  gap: var(--gap-3);
  min-width: 0;
}

.skill-card__avatar {
  display: grid;
  flex-shrink: 0;
  place-items: center;
  width: 36px;
  height: 36px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  background: var(--surface-sunken);
  color: var(--text-secondary);
}

.skill-card__avatar :deep(svg) {
  width: 16px;
  height: 16px;
}

.skill-card__identity {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.skill-card__name {
  color: var(--text-primary);
  font-size: var(--fs-title);
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.skill-card__slug {
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.skill-card__status {
  flex-shrink: 0;
  margin-top: 2px;
}

.skill-card__desc {
  display: -webkit-box;
  margin: 0;
  overflow: hidden;
  color: var(--text-secondary);
  font-size: var(--fs-ui);
  line-height: 1.55;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow-wrap: anywhere;
}

.skill-card__runtime {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.skill-card__tools {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 4px;
}

.skill-card__tool {
  padding: 1px 6px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-xs);
  background: var(--surface-sunken);
  color: var(--text-secondary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
}

.skill-card__tool--more,
.skill-card__tools--none {
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
}

.skill-card__foot {
  display: flex;
  align-items: center;
  gap: 2px;
  margin: auto -6px -6px;
  padding-top: var(--gap-2);
  border-top: 1px solid var(--border-subtle);
}

@media (max-width: 640px) {
  .skills-toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .skills-search {
    flex: 1 1 auto;
    min-width: 0;
  }

  .skills-toolbar__actions {
    flex-wrap: nowrap;
    overflow-x: auto;
    scrollbar-width: none;
  }

  .skills-toolbar__actions > * {
    flex-shrink: 0;
  }

  .skills-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .skill-card__foot :deep(button) {
    min-height: 40px;
  }
}
</style>
