import { createApp, h, ref } from 'vue'
import { createPinia } from 'pinia'
import Rail from '../../src/features/ai/components/AssistantSessionRail.vue'
import TaskSidebar from '../../src/features/ai/components/AssistantTaskSidebar.vue'
import { SidebarProvider } from '../../src/shared/components/ui/sidebar'
import { TooltipProvider } from '../../src/shared/components/ui/tooltip'
import { applyTheme } from '../../src/shared/lib/theme'
import '../../src/style.css'
const params = new URLSearchParams(location.search)
const guardian = params.get('mode') === 'guardian'
applyTheme(params.get('theme') || 'day', 'seal')
createApp({ setup() {
  const collapsed = ref(false), tab = ref('active'), event = ref(''), activeId = ref('first')
  const sessions = ref(params.has('empty') ? [] : [{ id: 'first', title: '第一条历史', updated_at: '2026-09-22T10:00:00' }, { id: 'second', title: '第二条历史' }])
  const archivedSessions = [{ id: 'archived', title: '归档历史', status: 'archived' }]
  const taskModel = ref({ plan: [], agents: [], sources: [{ id: 'source', kind: 'tool', label: '隔离数据来源' }], artifacts: [], summary: '', activityLines: [] })
  if (params.has('inspector')) return () => h(TooltipProvider, {}, () => h(SidebarProvider, {}, () => h('div', { style: 'display:flex;height:700px;width:100%' }, [
    h(TaskSidebar, { open: true, model: taskModel.value, ...(guardian ? { visibleTabs: ['sources', 'cabin'], title: '咨询详情' } : {}) }, guardian ? { cabin: () => h('p', { 'data-testid': 'guardian-cabin' }, '话题持仓背景插槽') } : undefined),
    h('button', { 'data-testid': 'add-agent', onClick: () => taskModel.value.agents.push({ id: 'fixture-agent', name: '隔离子进程', status: 'running', task: '隔离验证' }) }, '增加隔离子进程'),
  ])))
  return () => h(TooltipProvider, {}, () => h(SidebarProvider, {}, () => h('div', { style: 'display:flex;height:700px;max-height:100dvh;width:100%;' }, [
    h(Rail, { sessions: sessions.value, archivedSessions, activeId: activeId.value, railTab: tab.value, collapsed: collapsed.value,
      ...(guardian ? { archiveEnabled: false, batchEnabled: false, settingsEnabled: false, title: '历史话题', createLabel: '新建话题', searchPlaceholder: '搜索话题', brandLabel: '交易员', emptyDescription: '还没有话题', emptyReason: '新建话题开始讨论' } : {}),
      'onUpdate:collapsed': value => collapsed.value = value, 'onUpdate:railTab': value => tab.value = value,
      onSelect: id => { activeId.value = id; event.value = `select:${id}` }, onCreate: () => event.value = 'create', onRemove: id => event.value = `remove:${id}`, onArchive: id => event.value = `archive:${id}`, onRestore: id => event.value = `restore:${id}`, onSettings: () => event.value = 'settings', onBatch: value => event.value = `batch:${value.action}:${value.ids.join(',')}`,
    }), h('output', { 'data-testid': 'event', style: 'padding:24px' }, event.value),
  ])))
} }).use(createPinia()).mount('#app')
