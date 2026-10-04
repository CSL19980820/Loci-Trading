<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, onUnmounted, reactive, ref, useId, watch } from 'vue'
import { ChevronDown, Plus, RefreshCw, Upload } from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import { getSkills, getStrategies, removeSkill } from '@/shared/api/quant'
import type { Skill, StrategyInfo } from '@/shared/types/quant'
import PageHeader from '@/shared/components/layout/PageHeader.vue'
import { Button } from '@/shared/components/ui/button'
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/shared/components/ui/dropdown-menu'
import { confirmDangerous } from '@/shared/lib/confirm'
import { toErrorMessage } from '@/shared/lib/errors'
import QuantStrategiesPanel from './components/QuantStrategiesPanel.vue'
import ScreenSkillBundleImportDialog from './components/ScreenSkillBundleImportDialog.vue'
const QuantSkillsPanel = defineAsyncComponent(() => import('./components/QuantSkillsPanel.vue'))
const BacktestPanel = defineAsyncComponent(() => import('./components/QuantBacktestPanel.vue'))
const ResearchPanel = defineAsyncComponent(() => import('@/features/research/ResearchPanel.vue'))
const StrategyInstallPanel = defineAsyncComponent(() => import('./components/StrategyInstallPanel.vue'))
const router = useRouter(), route = useRoute(), panelId = useId()
type View = 'library' | 'backtest' | 'research' | 'install'
const parseView = (value: unknown): View => ['backtest', 'research', 'install'].includes(String(value)) ? value as View : 'library'
const activeTab = ref<View>(parseView(route.query.tab))
const strategies = ref<StrategyInfo[]>([]), skills = ref<Skill[]>([])
const loading = reactive({ strategies: false, skills: false })
const errors = reactive({ strategies: '', skills: '' })
const bundleImportOpen = ref(false)
const researchCode = computed(() => String(route.query.code || '').trim())
const tabs = [{ name: 'library', label: '策略库' }, { name: 'backtest', label: '回测' }]
let generation = 0
onUnmounted(() => { generation++ })

function redirectSettings(): boolean {
  const tab = String(route.query.tab || '')
  if (tab === 'sources' || tab === 'jobs') {
    void router.replace({ path: '/ops', query: { ...route.query, tab } })
    return true
  }
  if (tab === 'paper') { void router.replace('/agents'); return true }
  return false
}
watch(() => route.query.tab, value => {
  if (route.name !== 'quant' || redirectSettings()) return
  activeTab.value = parseView(value)
})
watch(activeTab, value => {
  if (route.name !== 'quant' || parseView(route.query.tab) === value) return
  void router.replace({ query: { ...route.query, tab: value === 'library' ? undefined : value } })
})

async function reload(): Promise<void> {
  const version = ++generation
  loading.strategies = true; loading.skills = true
  errors.strategies = ''; errors.skills = ''
  // Each result is committed independently; metadata or another section cannot block the library.
  await Promise.allSettled([
    getStrategies().then(rows => { if (version === generation) strategies.value = rows })
      .catch(error => { if (version === generation) errors.strategies = toErrorMessage(error, '策略加载失败') })
      .finally(() => { if (version === generation) loading.strategies = false }),
    getSkills().then(rows => { if (version === generation) skills.value = rows })
      .catch(error => { if (version === generation) errors.skills = toErrorMessage(error, '技能策略加载失败') })
      .finally(() => { if (version === generation) loading.skills = false }),
  ])
}
function goScreen(kind: 'engine' | 'skill', slug: string): void {
  void router.push({ path: '/screen-history', query: { select: `${kind}:${slug}` } })
}
function openCreate(source: string): void { void router.push({ path: '/strategy-converter', query: { source } }) }
async function uninstallSkill(skill: Skill): Promise<void> {
  if (!(await confirmDangerous(`确定卸载技能「${skill.name}」？`, '卸载策略', '卸载'))) return
  try { await removeSkill(skill.slug); skills.value = skills.value.filter(row => row.slug !== skill.slug); toast.success('已卸载') }
  catch (error) { toast.error(toErrorMessage(error, '卸载失败')) }
}
function imported(): void { activeTab.value = 'library'; void reload() }
onMounted(() => { if (!redirectSettings()) void reload() })
</script>

<template>
  <div class="strategy-page page-fill">
    <PageHeader title="策略" :tabs="tabs" :panel-id="panelId" v-model:tab="activeTab">
      <template #actions>
        <Button access="read" variant="ghost" size="icon-sm" aria-label="刷新策略" :disabled="loading.strategies || loading.skills" @click="reload"><RefreshCw /></Button>
        <Button variant="outline" size="sm" @click="bundleImportOpen = true"><Upload />导入策略</Button>
        <DropdownMenu>
          <DropdownMenuTrigger as-child><Button size="sm"><Plus />新建与工具<ChevronDown /></Button></DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem @select="openCreate('blank')">新建策略</DropdownMenuItem>
            <DropdownMenuItem @select="openCreate('description')">AI 编写</DropdownMenuItem>
            <DropdownMenuItem @select="openCreate('tdx')">导入 TDX 公式</DropdownMenuItem>
            <DropdownMenuItem @select="activeTab = 'install'">安装技能包</DropdownMenuItem>
            <DropdownMenuItem @select="activeTab = 'research'">研究工作台</DropdownMenuItem>
            <DropdownMenuItem @select="router.push('/screen-history')">选股工作台</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </template>
    </PageHeader>
    <div :id="panelId" class="strategy-body" role="tabpanel" :aria-label="activeTab === 'library' ? '策略库' : activeTab === 'backtest' ? '回测' : activeTab === 'install' ? '安装技能包' : '研究工作台'" tabindex="0">
      <template v-if="activeTab === 'library'">
        <section class="strategy-section" aria-label="规则策略">
          <h2 class="strategy-section-title">规则策略 <span>{{ strategies.length }}</span></h2>
          <Alert v-if="errors.strategies" variant="destructive"><AlertTitle>{{ errors.strategies }}</AlertTitle></Alert>
          <QuantStrategiesPanel :strategies="strategies" :loading="loading.strategies && !strategies.length" @open-screen="goScreen('engine', $event)" @import-bundle="bundleImportOpen = true" />
        </section>
        <section class="strategy-section" aria-label="技能策略">
          <h2 class="strategy-section-title">技能策略 <span>{{ skills.length }}</span></h2>
          <Alert v-if="errors.skills" variant="destructive"><AlertTitle>{{ errors.skills }}</AlertTitle></Alert>
          <QuantSkillsPanel :skills="skills" :loading="loading.skills && !skills.length" @open-screen="goScreen('skill', $event)" @remove="uninstallSkill" @refresh="reload" />
        </section>
      </template>
      <BacktestPanel v-else-if="activeTab === 'backtest'" :strategies="strategies" :loading="loading.strategies && !strategies.length" />
      <template v-else>
        <Button access="read" variant="ghost" size="sm" class="self-start" @click="activeTab = 'library'">返回策略库</Button>
        <ResearchPanel v-if="activeTab === 'research'" :initial-code="researchCode" />
        <StrategyInstallPanel v-else @installed="imported" @notice="toast.success" @error="toast.error" />
      </template>
    </div>
    <ScreenSkillBundleImportDialog v-model="bundleImportOpen" paste @imported="imported" />
  </div>
</template>

<style scoped>
.strategy-page { display:flex; flex-direction:column; min-width:0; min-height:0; height:100%; overflow:hidden; }
.strategy-body { display:flex; flex:1 1 auto; flex-direction:column; gap:18px; min-width:0; min-height:0; overflow:auto; padding:4px 0 16px; }
.strategy-section { display:flex; flex-direction:column; min-width:0; min-height:320px; flex:0 0 auto; gap:8px; }
.strategy-section-title { display:flex; align-items:center; gap:8px; margin:0; font-size:14px; font-weight:600; color:var(--text-primary); }
.strategy-section-title span { color:var(--text-tertiary); font-size:12px; font-weight:400; }
@media(max-width:767px) { .strategy-body { gap:14px; } .strategy-section { min-height:280px; } }
</style>
