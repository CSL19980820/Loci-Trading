<script setup lang="ts">
import { Item } from '@/shared/components/ui/item'
import { computed, ref, watch } from 'vue'
import { ChevronRight } from '@lucide/vue'
import { Badge } from '@/shared/components/ui/badge'
import RecordDetailsDialog from '@/shared/components/ui/RecordDetailsDialog.vue'
import Descriptions from '@/shared/components/ui/Descriptions.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import type { GuardianExperience } from '@/shared/types/guardian'

const props = defineProps<{ experience?: GuardianExperience }>()
const labels = { proposed: '待验证', supported: '有证据支持', refuted: '已反证', inconclusive: '尚无定论', corrected: '已纠正' }
const reportLabel = (key: string) => key.replace('weekly:', '周复盘 · ').replace('daily:', '日复盘 · ').replace('tool:', '工具记录 · ').replace('experience:', '经验引用 · ')
const selectedId = ref('')
const selected = computed(() => props.experience?.items.find(item => item.id === selectedId.value))
const detailOpen = computed({ get: () => Boolean(selected.value), set: (open: boolean) => { if (!open) selectedId.value = '' } })
watch(() => props.experience, () => { if (!selected.value) selectedId.value = '' })
</script>

<template>
  <section class="experience-panel" aria-label="经验沉淀">
    <template v-if="experience?.items.length">
      <div class="experience-columns" aria-hidden="true"><span>序号</span><span>状态</span><span>经验</span><span>验证</span><span>详情</span></div>
      <ol class="experience-list">
        <li v-for="(item, index) in experience.items" :key="item.id">
          <Item as="button" type="button" class="experience-row" :aria-label="`查看经验 ${index + 1}：${item.hypothesis}`" @click="selectedId = item.id">
            <span class="experience-number">{{ String(index + 1).padStart(2, '0') }}</span>
            <Badge variant="secondary" class="experience-status">{{ labels[item.status] }}</Badge>
            <span class="experience-claim">{{ item.hypothesis }}</span>
            <span class="experience-validation"><span class="experience-validation__label">验证</span>{{ item.validation_plan }}</span>
            <span class="experience-detail-link"><span>{{ item.evidence_ids.length }} 条来源</span><ChevronRight :size="15" aria-hidden="true" /></span>
          </Item>
        </li>
      </ol>
    </template>
    <EmptyState v-else compact :description="experience ? '暂无经验记录' : '经验加载失败，请刷新重试'" />

    <RecordDetailsDialog v-model:open="detailOpen" title="经验详情">
      <Descriptions v-if="selected" :items="[
        { key:'status', label:'验证状态', value:labels[selected.status] },
        { key:'report', label:'来源复盘', value:experience?.origins?.[selected.id] ? reportLabel(experience.origins[selected.id]!.source_report) : undefined },
        { key:'hypothesis', label:'经验内容', value:selected.hypothesis, wide:true },
        { key:'validation', label:'验证计划', value:selected.validation_plan, wide:true },
        { key:'sources', label:'证据引用', value:selected.evidence_ids.map(reportLabel).join(String.fromCharCode(10)), wide:true },
      ]">
        <template #status><Badge variant="secondary">{{ labels[selected.status] }}</Badge></template>
      </Descriptions>
    </RecordDetailsDialog>
  </section>
</template>

<style scoped>
.experience-panel { display:flex; flex-direction:column; flex:1; min-height:0; min-width:0; overflow:auto; padding:0 0 12px; }
.experience-columns,.experience-row { display:grid; grid-template-columns:34px 100px minmax(0,1.1fr) minmax(0,1fr) 80px; gap:14px; align-items:center; }
.experience-columns { min-height:30px; padding:0 14px; color:var(--text-tertiary); font-size:11px; flex:none; }
.experience-list { list-style:none; padding:0; margin:0; border:1px solid var(--border-subtle); border-radius:10px; overflow:hidden; flex:none; }
.experience-list li + li { border-top:1px solid var(--border-subtle); }
.experience-row { width:100%; height:88px; min-height:88px; max-height:88px; padding:10px 14px; border:0; background:var(--surface); color:var(--text-primary); font:inherit; text-align:left; cursor:pointer; }
.experience-row:hover { background:var(--surface-hover); }
.experience-row:focus-visible { outline:2px solid var(--seal); outline-offset:-3px; border-radius:6px; }
.experience-number { font:12px var(--mono); color:var(--text-tertiary); }
.experience-status { width:fit-content; max-width:100%; white-space:nowrap; font-size:11px; font-weight:500; }
.experience-claim,.experience-validation { min-width:0; overflow:hidden; display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:3; line-height:1.7; font-size:13px; overflow-wrap:anywhere; }
.experience-validation { font-size:12px; color:var(--text-secondary); }
.experience-validation__label { display:none; }
.experience-detail-link { display:flex; align-items:center; justify-content:flex-end; gap:4px; font-size:11px; white-space:nowrap; color:var(--text-tertiary); }
@media(max-width:767px) {
 .experience-panel { overflow:visible; padding-bottom:10px; }
 .experience-columns { display:none; }
 .experience-row { height:142px; min-height:142px; max-height:142px; grid-template-columns:24px minmax(0,1fr) auto; grid-template-rows:24px 46px 34px; gap:6px 8px; padding:12px; align-content:center; }
 .experience-number { grid-column:1; grid-row:1; }
 .experience-status { grid-column:2; grid-row:1; }
 .experience-detail-link { grid-column:3; grid-row:1; }
 .experience-claim { grid-column:1/-1; grid-row:2; -webkit-line-clamp:2; font-size:13px; line-height:23px; align-self:start; }
 .experience-validation { grid-column:1/-1; grid-row:3; -webkit-line-clamp:2; line-height:17px; font-size:11px; }
 .experience-validation__label { display:inline; color:var(--text-tertiary); margin-right:7px; }
}
</style>
