# 报告视觉设计规范

设计目标：报告应像一份严肃的投研工作底稿，而不是临时拼接的 Markdown。Markdown、HTML、PDF 共用相同信息架构；PDF 可额外使用封面图作为视觉基底，但正文仍以可读性和稳定版式优先。

## 版式原则

- 页面：A4，正文最大宽度约 1040px，打印边距 16mm。
- 网格：8px 间距系统，区块间距 24px，章节间距 32px。
- 字体：系统中文字体栈，正文 14px，行高 1.65。
- 标题：H1 28-32px，H2 22-24px，H3 18-20px。
- 表格：全宽、细边框、浅灰表头、数字右对齐优先。
- 色彩：专业浅色主题，不使用大面积渐变、不使用装饰性漂浮图形。

## 设计令牌

```css
:root {
  --report-bg: #f6f8fb;
  --report-surface: #ffffff;
  --report-ink: #172033;
  --report-muted: #5f6b7a;
  --report-border: #d9e0ea;
  --report-primary: #176b87;
  --report-accent: #b7791f;
  --report-risk: #b42318;
  --report-success: #1f7a4d;
}
```

## PDF 封面图资产

封面图是 image generation 生成的位图资产，作为 PDF/HTML 首页的视觉基底，不参与数据计算。

- 默认路径：`assets/report-cover.png`
- 建议尺寸：`1600x900` 或 `1920x1080`
- 风格：专业金融研究工作台、克制、无真实品牌、无股票代码、无可误读文字。
- 禁止：收益承诺、上涨箭头暗示、具体公司 Logo、真实券商界面截图、夸张营销风。

如果封面图不存在，报告自动使用纯 CSS 封面，不影响输出。

## Markdown 定稿约束

Markdown 必须保持稳定标题和章节顺序。不要因为数据为空删除章节；空数据用固定占位文案说明。这样 Codex、PDF 转换器和下游脚本都能稳定定位内容。
