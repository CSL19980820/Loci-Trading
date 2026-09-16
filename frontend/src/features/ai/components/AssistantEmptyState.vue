<script setup lang="ts">
import { ArrowRight } from '@element-plus/icons-vue'
export type AssistantPromptCard = {
  id: string
  title: string
  hint: string
  prompt: string
}

withDefaults(defineProps<{
  prompts: AssistantPromptCard[]
  /** 忙态 / 未配模型时父级会静默丢弃 pick，按钮同步置灰而不是点了没反应 */
  busy?: boolean
  providerReady?: boolean
}>(), {
  busy: false,
  providerReady: true,
})

const emit = defineEmits<{ pick: [prompt: string] }>()
</script>

<template>
  <div class="assistant-empty" data-testid="assistant-empty">
    <header class="assistant-empty__lead"><h3>开始对话</h3><p>选择示例，或直接输入问题</p></header>
    <ul class="assistant-empty__list" aria-label="提问示例">
      <li v-for="card in prompts" :key="card.id">
        <el-button class="assistant-empty__row" :disabled="busy || !providerReady" :aria-label="card.title" :title="'填入输入框：' + card.hint" @click="emit('pick', card.prompt)">
          <span class="assistant-empty__copy"><strong>{{ card.title }}</strong><span>{{ card.hint }}</span></span>
          <el-icon class="assistant-empty__arrow" aria-hidden="true"><ArrowRight /></el-icon>
        </el-button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.assistant-empty { display: flex; min-height: 0; min-width: 0; flex: 1; flex-direction: column; align-items: center; justify-content: safe center; gap: var(--gap-3); overflow: auto; padding-block: var(--gap-4); scrollbar-width: thin; }
.assistant-empty__lead { width: 100%; max-width: 44rem; }
.assistant-empty__lead h3 { margin: 0; color: var(--ink); font-size: var(--ai-fs-title); font-weight: 650; }
.assistant-empty__lead p { margin: var(--gap-1) 0 0; font-size: var(--ai-fs-body); color: var(--mist); }
.assistant-empty__list {
  /* 16rem 是双行示例的最小阅读宽度，44rem 与原示例区宽度一致。 */
  display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 16rem), 1fr)); gap: var(--gap-2); width: min(100%, 44rem); margin: 0; padding: 0; list-style: none;
}
.assistant-empty__list li { min-width: 0; }
.assistant-empty__row {
  --el-button-bg-color: var(--surface); --el-button-text-color: var(--ink); --el-button-border-color: var(--rule); --el-button-hover-bg-color: var(--surface-hover); --el-button-hover-text-color: var(--ink); --el-button-hover-border-color: var(--seal-border);
  width: 100%; height: auto; margin: 0; padding: var(--gap-3); border-radius: var(--ai-r-card); text-align: left; white-space: normal;
}
.assistant-empty__row :deep(> span) { display: flex; align-items: center; gap: var(--gap-2); width: 100%; min-width: 0; }
.assistant-empty__copy { display: flex; flex: 1; min-width: 0; flex-direction: column; gap: var(--gap-1); }
.assistant-empty__copy strong { font-size: var(--ai-fs-body); font-weight: 600; line-height: 1.5; }
.assistant-empty__copy > span { font-size: var(--ai-fs-aux); color: var(--mist); line-height: 1.5; overflow-wrap: anywhere; }
.assistant-empty__arrow { flex-shrink: 0; color: var(--seal-ink); }
.assistant-empty__row:focus-visible { outline: 2px solid var(--seal); outline-offset: -2px; }
</style>
