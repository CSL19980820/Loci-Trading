<script setup lang="ts">
import { computed } from 'vue'

import { BRAND_MARK, BRAND_NAME } from '@/shared/lib/brand'
import { APP_VERSION } from '@/shared/lib/release'

/**
 * 品牌侧的装饰曲线。**不是行情**，只是一条平滑上行的抽象形态，
 * 和 Stripe / Linear 登录页的背景图形同一性质：给画面重量，不承载数字。
 * 真接行情需要免鉴权的公开快照端点，见 README「品牌侧要不要接真数据」。
 */
const SHAPE = [0.34, 0.28, 0.42, 0.38, 0.5, 0.46, 0.58, 0.55, 0.66, 0.74, 0.88]
const VIEW = { w: 640, h: 260 } as const

/** Catmull-Rom 转三次贝塞尔：折线太硬像心电图，平滑后才是图形。 */
function smooth(pts: Array<[number, number]>): string {
  let d = `M${pts[0][0]},${pts[0][1]}`
  for (let i = 0; i < pts.length - 1; i += 1) {
    const p0 = pts[i - 1] ?? pts[i]
    const p1 = pts[i]
    const p2 = pts[i + 1]
    const p3 = pts[i + 2] ?? p2
    d +=
      ` C${p1[0] + (p2[0] - p0[0]) / 6},${p1[1] + (p2[1] - p0[1]) / 6}` +
      ` ${p2[0] - (p3[0] - p1[0]) / 6},${p2[1] - (p3[1] - p1[1]) / 6}` +
      ` ${p2[0]},${p2[1]}`
  }
  return d
}

const points = computed<Array<[number, number]>>(() => {
  const step = VIEW.w / (SHAPE.length - 1)
  return SHAPE.map((v, i) => [i * step, (1 - v) * VIEW.h] as [number, number])
})
const linePath = computed(() => smooth(points.value))
const areaPath = computed(() => `${linePath.value} L${VIEW.w},${VIEW.h} L0,${VIEW.h} Z`)

const capabilities = [
  { name: '盯盘', desc: '分时异动、二波信号、龙虎盘口' },
  { name: '复盘', desc: '每一笔的进出场与归因' },
  { name: '实盘', desc: '战法信号直接落成下单预案' },
]
</script>

<template>
  <!--
    非壳内页：品牌侧固定深色，不跟随 day / paper / night / ink 四档外观。
    这里是门面画面而不是工作面，四档令牌里没有对应层级，颜色只能就地定义。
    表单侧仍然跟随外观（见 LoginView 的 .auth-panel）。
  -->
  <aside class="brand-side">
    <div class="brand-side__glow" aria-hidden="true" />
    <div class="brand-side__glow2" aria-hidden="true" />
    <div class="brand-side__dots" aria-hidden="true" />

    <header class="brand-side__id">
      <span class="brand-side__mark">{{ BRAND_MARK }}</span>
      <span class="brand-side__name">{{ BRAND_NAME }}</span>
    </header>

    <h1 class="brand-side__claim">看得见的<br />每一次买入与卖出</h1>
    <p class="brand-side__tag">多战法量化工作台</p>

    <section class="brand-side__card">
      <svg
        class="brand-side__curve"
        :viewBox="`0 0 ${VIEW.w} ${VIEW.h}`"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <defs>
          <linearGradient id="brand-curve-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="var(--seal)" stop-opacity=".30" />
            <stop offset="100%" stop-color="var(--seal)" stop-opacity="0" />
          </linearGradient>
        </defs>
        <path :d="areaPath" fill="url(#brand-curve-fill)" />
        <path :d="linePath" fill="none" stroke="var(--seal)" stroke-width="2" />
      </svg>

      <ul class="brand-side__caps">
        <li v-for="cap in capabilities" :key="cap.name">
          <b>{{ cap.name }}</b>
          <span>{{ cap.desc }}</span>
        </li>
      </ul>
    </section>

    <footer class="brand-side__foot">
      <span>v{{ APP_VERSION }} 群龙</span>
      <span>数字由量化引擎产出，不由 AI 编造</span>
    </footer>
  </aside>
</template>

<style scoped>
.brand-side {
  position: relative;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  /* 登录页专属深色层级：四档令牌最深的 --n-4 也比它亮，无法复用 */
  background: #0b0d12;
  padding: var(--gap-4) calc(var(--gap-4) * 1.5);
  isolation: isolate;
}
.brand-side > * {
  position: relative;
  z-index: 1;
}
/* 暖冷双光：只铺一层大范围低透明度会糊成红雾，成对出现才有空间感 */
.brand-side__glow,
.brand-side__glow2,
.brand-side__dots {
  position: absolute;
  z-index: 0;
  pointer-events: none;
}
.brand-side__glow {
  inset: -55% 30% 40% -45%;
  background: radial-gradient(
    closest-side,
    color-mix(in oklab, var(--seal) 22%, transparent),
    color-mix(in oklab, var(--seal) 4%, transparent) 50%,
    transparent 74%
  );
}
.brand-side__glow2 {
  inset: 45% -40% -45% 40%;
  background: radial-gradient(closest-side, rgba(58, 104, 180, 0.15), transparent 70%);
}
/*
 * 点阵必须配径向遮罩往外淡出。没有遮罩时它在整幅上均匀铺开，会和压在上面的
 * 52px 标题抢注意力——「一个你能注意到的底纹，就是一个正在和文字竞争的底纹」。
 */
.brand-side__dots {
  inset: 0;
  background-image: radial-gradient(
    circle at 1.5px 1.5px,
    rgba(255, 255, 255, 0.05) 1.5px,
    transparent 0
  );
  background-size: 36px 36px;
  -webkit-mask-image: radial-gradient(ellipse 90% 70% at 26% 38%, #000 48%, transparent 100%);
  mask-image: radial-gradient(ellipse 90% 70% at 26% 38%, #000 48%, transparent 100%);
}

.brand-side__id {
  display: flex;
  align-items: center;
  gap: var(--gap-3);
}
.brand-side__mark {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: var(--seal);
  color: var(--on-primary);
  font: 800 20px/1 var(--mono);
}
.brand-side__name {
  font-size: 20px;
  font-weight: 700;
  letter-spacing: 0.03em;
  color: #f2f5f9;
}

/*
 * 页面上最大的元素：门面页的视觉锚点，不受工作台 ≤18px 标题约束。
 * 上下留白用 vh 弹性：1080 高的屏上如果写死 56px，卡片下方会空出一整块。
 */
.brand-side__claim {
  margin: clamp(48px, 8vh, 108px) 0 0;
  font-size: clamp(30px, 3.4vw, 52px);
  line-height: 1.26;
  font-weight: 700;
  /*
   * 负字距。ui-spec 里中文标题的 +0.03em 是给 14px 密排正文用的，48px 以上
   * 再撑开就散架。中文不能像西文那样负到 -0.03em（会挤字），-0.01em 是上限。
   */
  letter-spacing: -0.01em;
  color: #f2f5f9;
}
.brand-side__tag {
  margin: 18px 0 0;
  font-size: 16px;
  letter-spacing: 0.04em;
  color: rgba(233, 238, 245, 0.6);
}

/* 上下都吃 auto：高屏上剩余空间均分到「陈述↔卡片」和「卡片↔页脚」，不堆在底部 */
.brand-side__card {
  position: relative;
  margin: auto 0;
  max-width: 624px;
  border: 1px solid rgba(255, 255, 255, 0.09);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.035);
  overflow: hidden;
}
/* 曲线区高度写死，caps 的 padding-top 跟着它走：用百分比会随卡片高度浮动，压到文字上 */
.brand-side__curve {
  position: absolute;
  inset: 0 0 auto;
  width: 100%;
  height: 132px;
  opacity: 0.9;
}
.brand-side__caps {
  position: relative;
  margin: 0;
  padding: 148px 24px 8px;
  list-style: none;
}
.brand-side__caps li {
  display: flex;
  align-items: baseline;
  gap: var(--gap-3);
  padding: 16px 0;
  border-top: 1px solid rgba(255, 255, 255, 0.07);
}
.brand-side__caps li:first-child {
  border-top: 0;
}
.brand-side__caps b {
  flex: none;
  width: 3em;
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: #f2f5f9;
}
.brand-side__caps span {
  font-size: 13px;
  color: rgba(233, 238, 245, 0.52);
}

.brand-side__foot {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: var(--gap-2);
  padding-top: var(--gap-4);
  font-size: 12px;
  letter-spacing: 0.03em;
  color: rgba(233, 238, 245, 0.34);
}

/* 窄屏：收成一条横帽，只保留品牌与一行陈述 */
@media (max-width: 1080px) {
  .brand-side {
    padding: var(--gap-3) var(--gap-4);
  }
  .brand-side__claim {
    margin-top: 18px;
    font-size: 24px;
    line-height: 1.35;
  }
  .brand-side__claim br {
    display: none;
  }
  .brand-side__tag {
    margin-top: 6px;
    font-size: 13px;
  }
  .brand-side__card,
  .brand-side__foot {
    display: none;
  }
}
</style>
