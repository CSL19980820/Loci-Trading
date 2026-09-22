<script setup lang="ts">
/**
 * 全局命令面板（⌘K）。一处入口跳所有页面、触发壳层动作、切换外观。
 *
 * 数据源与侧栏同一份（useSidebarNav 的分组），不另维护一张表。
 * 面板只负责「选中 → 分发」：路由跳转自己做；记候选/预案抛给 App.vue 的 RecordDialog。
 */
import {
  ArrowRight,
  Brush,
  ClipboardPen,
  CornerDownLeft,
  Moon,
  Palette,
  PenLine,
  RefreshCw,
  Settings,
  ShieldCheck,
  Sun,
  User,
} from '@lucide/vue'
import { computed, type Component } from 'vue'
import { useRouter } from 'vue-router'

import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/shared/components/ui/command'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/shared/components/ui/dialog'
import { commandPaletteOpen, requestRecord } from '@/shared/lib/commandPalette'
import { NAV_LABELS } from '@/shared/lib/navLabels'
import { useThemeStore } from '@/shared/stores/theme'
import { useUserStore } from '@/shared/stores/user'
import { useSidebarNav } from './composables/useSidebarNav'

const emit = defineEmits<{
  /** 请求打开主题弹窗：该弹窗归侧栏持有 */
  theme: []
  reload: []
}>()

const router = useRouter()
const themeStore = useThemeStore()
const userStore = useUserStore()
const { navGroups } = useSidebarNav()

type Entry = { id: string; label: string; hint?: string; icon: Component; run: () => void }

const pageEntries = computed<Entry[]>(() => {
  const pages: Entry[] = navGroups.flatMap((group) =>
    group.items.map((item) => ({
      id: `page:${item.path}`,
      label: item.label,
      hint: group.label,
      icon: item.icon,
      run: () => void router.push(item.path),
    })),
  )
  if (userStore.isAdmin) pages.push(
    { id: 'page:/ops', label: NAV_LABELS.ops.title, hint: '系统', icon: Settings, run: () => void router.push('/ops') },
    { id: 'page:/account', label: NAV_LABELS.account.title, hint: '系统', icon: User, run: () => void router.push('/account') },
  )
  if (userStore.isAdmin) {
    pages.push({
      id: 'page:/admin',
      label: NAV_LABELS.admin.title,
      hint: '系统',
      icon: ShieldCheck,
      run: () => void router.push('/admin'),
    })
  }
  return pages
})

const actionEntries = computed<Entry[]>(() => [
  { id: 'act:candidate', label: '记一条候选', hint: 'C', icon: PenLine, run: () => requestRecord('candidate') },
  { id: 'act:plan', label: '记一条预案', hint: 'P', icon: ClipboardPen, run: () => requestRecord('plan') },
  { id: 'act:reload', label: '刷新本页数据', icon: RefreshCw, run: () => emit('reload') },
  { id: 'act:theme', label: '主题与外观…', icon: Palette, run: () => emit('theme') },
].filter((entry) => userStore.canWrite || !['act:candidate', 'act:plan'].includes(entry.id)))

const appearanceEntries = computed<Entry[]>(() =>
  themeStore.appearances.map((option) => ({
    id: `ap:${option.id}`,
    label: `外观：${option.label}`,
    hint: option.hint,
    icon: option.mode === 'dark' ? Moon : Sun,
    run: () => themeStore.setAppearance(option.id),
  })),
)

const primaryEntries = computed<Entry[]>(() =>
  themeStore.primaries.map((option) => ({
    id: `pr:${option.id}`,
    label: `主色：${option.label}`,
    icon: Brush,
    run: () => themeStore.setPrimary(option.id),
  })),
)

const groups = computed(() => [
  { id: 'pages', heading: '页面', entries: pageEntries.value, showGo: true },
  { id: 'actions', heading: '操作', entries: actionEntries.value, showGo: false },
  { id: 'appearance', heading: '外观', entries: [...appearanceEntries.value, ...primaryEntries.value], showGo: false },
])

function pick(entry: Entry): void {
  commandPaletteOpen.value = false
  // 先关面板再执行：路由跳转 / 开弹窗都不该和面板的关闭动画抢焦点
  window.setTimeout(entry.run, 0)
}
</script>

<template>
  <Dialog v-model:open="commandPaletteOpen">
    <DialogContent
      class="command-palette top-[14vh] translate-y-0 gap-0 overflow-hidden p-0 sm:max-w-[600px]"
      :show-close-button="false"
    >
      <DialogHeader class="sr-only">
        <DialogTitle>命令面板</DialogTitle>
        <DialogDescription>搜索页面、执行操作或切换外观</DialogDescription>
      </DialogHeader>
      <Command class="rounded-none bg-transparent">
        <CommandInput placeholder="搜索页面、操作或外观…" />
        <CommandList class="max-h-[min(60vh,420px)]">
          <CommandEmpty>
            <div class="command-palette__empty">没有匹配的页面或操作</div>
          </CommandEmpty>
          <CommandGroup v-for="group in groups" :key="group.id" :heading="group.heading">
            <CommandItem
              v-for="entry in group.entries"
              :key="entry.id"
              :value="`${entry.label} ${entry.hint ?? ''}`"
              class="command-palette__item"
              @select="pick(entry)"
            >
              <component :is="entry.icon" class="command-palette__icon" aria-hidden="true" />
              <span class="command-palette__label">{{ entry.label }}</span>
              <kbd v-if="group.id === 'actions' && entry.hint" class="command-palette__kbd">{{ entry.hint }}</kbd>
              <span v-else-if="entry.hint" class="command-palette__hint">{{ entry.hint }}</span>
              <ArrowRight v-if="group.showGo" class="command-palette__go" aria-hidden="true" />
            </CommandItem>
          </CommandGroup>
        </CommandList>
        <div class="command-palette__foot" aria-hidden="true">
          <span><kbd>↑</kbd><kbd>↓</kbd> 选择</span>
          <span><kbd><CornerDownLeft class="size-3" /></kbd> 打开</span>
          <span><kbd>esc</kbd> 关闭</span>
        </div>
      </Command>
    </DialogContent>
  </Dialog>
</template>

<style scoped>
.command-palette {
  border-radius: var(--radius-xl);
  border-color: var(--border-subtle);
  background: var(--surface-raised);
  box-shadow: var(--shadow-lg);
}

.command-palette :deep([data-slot='command-input-wrapper']) {
  height: 52px;
  padding: 0 var(--gap-4);
  border-bottom: 1px solid var(--border-subtle);
}

.command-palette :deep([data-slot='command-input']) {
  font-size: var(--fs-title);
  color: var(--text-primary);
}

.command-palette :deep([data-slot='command-group']) {
  padding: var(--gap-2);
}

.command-palette :deep([data-slot='command-group-heading']) {
  padding: var(--gap-1) var(--gap-2);
  font-size: var(--fs-kicker);
  font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--text-tertiary);
}

.command-palette__item {
  height: 36px;
  padding: 0 var(--gap-2);
  border-radius: var(--radius);
  font-size: var(--fs-ui);
  color: var(--text-primary);
  cursor: pointer;
}

.command-palette__icon {
  width: 16px;
  height: 16px;
  color: var(--text-tertiary);
}

.command-palette__item[data-highlighted] .command-palette__icon {
  color: var(--seal);
}

.command-palette__label {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.command-palette__hint {
  font-size: var(--fs-aux);
  color: var(--text-tertiary);
}

.command-palette__go {
  width: 14px;
  height: 14px;
  color: var(--text-tertiary);
  opacity: 0;
  transform: translateX(-4px);
  transition:
    opacity var(--dur-fast) var(--ease),
    transform var(--dur-fast) var(--ease);
}

.command-palette__item[data-highlighted] .command-palette__go {
  opacity: 1;
  transform: none;
}

.command-palette__kbd,
.command-palette__foot kbd {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 20px;
  padding: 0 5px;
  border: 1px solid var(--border-default);
  border-bottom-width: 2px;
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text-secondary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  line-height: 1;
}

.command-palette__empty {
  padding: var(--gap-6) var(--gap-4);
  color: var(--text-tertiary);
  font-size: var(--fs-ui);
}

.command-palette__foot {
  display: flex;
  align-items: center;
  gap: var(--gap-4);
  height: 40px;
  padding: 0 var(--gap-4);
  border-top: 1px solid var(--border-subtle);
  background: var(--surface-sunken);
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}

.command-palette__foot span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
</style>
