<script setup lang="ts">
import { BRAND_MARK, BRAND_NAME } from '@/shared/lib/brand'
import { APP_VERSION } from '@/shared/lib/release'

/** 登录前只展示产品模块，不展示未获取的行情或运行状态。 */
const lanes = [
  { code: 'MARKET', name: '行情', desc: '分时 · 盘口 · 异动' },
  { code: 'STRATEGY', name: '策略', desc: '信号 · 研究 · 预案' },
  { code: 'AGENT', name: '助手', desc: '任务 · 执行 · 结果' },
  { code: 'REVIEW', name: '复盘', desc: '样本 · 胜率 · 归因' },
] as const
</script>

<template>
  <aside class="brand-side" aria-label="品牌">

    <header class="brand-side__id">
      <span class="brand-side__mark">{{ BRAND_MARK }}</span>
      <div class="brand-side__id-text">
        <strong class="brand-side__name">{{ BRAND_NAME }}</strong>
        <span class="brand-side__tag">量化工作台</span>
      </div>
      <span class="brand-side__ver">v{{ APP_VERSION }}</span>
    </header>

    <section class="brand-side__tape" aria-label="工作台模块">
      <div class="brand-side__tape-head">
        <span>模块</span>
        <span>工作区</span>
        <span>内容</span>
      </div>
      <ul class="brand-side__lanes">
        <li v-for="lane in lanes" :key="lane.code">
          <code>{{ lane.code }}</code>
          <b>{{ lane.name }}</b>
          <span>{{ lane.desc }}</span>
        </li>
      </ul>
    </section>

    <footer class="brand-side__foot">
      <span>群龙</span>
      <span>数字由量化引擎产出，不由 AI 编造</span>
    </footer>
  </aside>
</template>

<style scoped>
.brand-side {
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  gap: var(--gap-4);
  padding: var(--gap-4);
  border-right: 1px solid var(--rule);
  background: var(--surface-sunken);
}
.brand-side__id { display: flex; align-items: center; gap: var(--gap-2); }
.brand-side__mark {
  display: grid;
  place-items: center;
  width: var(--ctl-h);
  height: var(--ctl-h);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--seal-soft);
  color: var(--seal-ink);
  font: 700 var(--fs-aux) / 1 var(--mono);
}
.brand-side__id-text { display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--gap-2); min-width: 0; }
.brand-side__name { color: var(--ink); font-size: var(--fs-title); font-weight: 700; }
.brand-side__tag, .brand-side__ver { color: var(--muted); font-size: var(--fs-aux); }
.brand-side__ver { margin-left: auto; font-family: var(--mono); white-space: nowrap; }
.brand-side__tape { margin-block: auto; border: 1px solid var(--rule); border-radius: var(--radius); background: var(--surface); overflow: hidden; }
.brand-side__tape-head, .brand-side__lanes li {
  display: grid;
  grid-template-columns: 7em 3em minmax(0, 1fr);
  align-items: center;
  gap: var(--gap-2);
  padding: var(--gap-3);
}
.brand-side__tape-head { color: var(--mist); font-size: var(--fs-aux); background: var(--sheet-alt); }
.brand-side__lanes { list-style: none; margin: 0; padding: 0; }
.brand-side__lanes li { border-top: 1px solid var(--rule-soft); }
.brand-side__lanes code { color: var(--seal-ink); font: 600 var(--fs-kicker) / 1.4 var(--mono); letter-spacing: .04em; }
.brand-side__lanes b { color: var(--ink); font-size: var(--fs-body); }
.brand-side__lanes span { color: var(--muted); font-size: var(--fs-aux); overflow-wrap: anywhere; }
.brand-side__foot { display: flex; flex-wrap: wrap; justify-content: space-between; gap: var(--gap-2); color: var(--mist); font-size: var(--fs-aux); }
@media (max-width: 980px) {
  .brand-side { padding: var(--gap-3); border-right: 0; border-bottom: 1px solid var(--rule); }
  .brand-side__tape, .brand-side__foot { display: none; }
}
</style>
