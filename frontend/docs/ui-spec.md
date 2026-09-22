# Loci UI · 设计参考（2026-09 重构后）

这是一份辅助设计材料，不是冻结界面的规则；所有建议都可以因用户需求、可访问性、性能和新技术而调整。
当前视觉方向与实现契约见 `docs/redesign-brief-2026-09-18.md`（含令牌表与共享组件 API）。本文只讲「为什么这样」。

## 方向

Loci 是个人量化工作台：盘面、候选池、选股、工坊、智能体、胜率、设置。参照 Linear / Vercel Dashboard / Raycast / shadcn dashboard 一路：

- **安静的表面层级**：画布 `--surface-canvas` → 面板 `--surface` → 浮层 `--surface-raised`，靠留白与极淡 hairline（`--border-subtle`）分区，不靠粗边框与底色块。
- **一个强调色**：`--seal` 只用于「当前 / 主操作 / 选中」；涨跌与状态色只出现在数字、chip 和状态点上。
- **紧凑读数**：`StatCard` 默认将标签和主值同排；有必要的统计上下文才另起一行。常规字号 18–22px，不为大数字、图标或模块说明固定撑出三行。金额、单位、正负号及样本口径保留完整；极窄容器允许自然换行，不裁数据。
- **保留与去框**：收益、权益等主读数保留轻量卡片；候选数量、平台计数、工具配额及行情摘要使用 `stat-strip--plain`，不另套一排大盒子。计算说明统一放在已有口径入口，动态样本数和风险提示保留。
- **清晰的字号阶梯**：11 kicker / 12 aux / 13 ui / 14 body / 15 title / 20 hero / 24 tape / 28 display。界面字默认 13px。
- **bento 网格**：内容用不等宽卡片组合（2:1、1:1:1），表格只是卡片里的一种内容。
- **移动优先的弹层**：≤640 时 Dialog / Sheet / Drawer 自动变贴底 sheet；表格换成卡片列表；底部毛玻璃导航。

## 壳层

- 侧栏 236px（可折叠到 60px）：品牌 + 搜索入口（⌘K）+ 分组菜单 + 底部固定项 + 用户卡。选中项是浮起的白色药片 + 左侧 2px 主色刻线。
- 全局命令面板（`CommandPalette`）：跳页面、记候选/预案、切外观与主色。
- 路由页保留一个 `PageHeader` 标题及必要动作，不重复眉题、标题或模块用途描述。桌面列表按窗口分配可用高度，只让长内容区域滚动；窄屏保留内容可达性，不靠裁剪模拟单屏。
- 跨页状态（初始密码 / 加载失败 / 同步中 / 选股在跑）走右上角 toast 气泡（`useShellNotices`），不再占一条常驻的状态轨。

## 组件与实现

原语在 `shared/components/ui/<name>/`（shadcn-vue / Reka 源码，可直接改）；组合控件在 `shared/components/ui/app/`；页面级组合（`PageHeader`、`PageToolbar`、`PageTabs`、`StatCard`、`EmptyState`、`BasicTable`、`BasicForm`）在 `shared/components/ui/` 与 `shared/components/layout/`。
令牌在 `style.base.css`（day）与 `style.theme.css`（paper / night / ink 覆盖），Tailwind 语义类在 `style.tw-theme.css`。图表 / 编辑器通过 `getComputedStyle` 读的令牌一律是 sRGB 字面量。

## 主题

四档外观 `day / paper / night / ink` × 八档内置主色 + 自定义主色（OKLCH 钉亮度、WCAG 收敛）。深色档的面板与画布必须能分层，阴影更重并带 1px 亮边；文字三级色在最亮承载面上仍 ≥ 4.5:1（见 `scripts/_palette.mjs` 的校验输出）。

## 数据密集页面

名称列 = 名称（加粗）+ 代码（等宽小字）两行；数字列右对齐等宽；涨跌 chip 带符号与底色；行高 36px；表头 12px 三级色下沉底。
手机端优先卡片列表（名称 + 关键数字 + 一行次要信息，整卡可点）；确实需要表格时首列冻结、其余横滑。
长名称与长文本折行、展开或进详情；口径说明进 tooltip。

## 表单与反馈

桌面 label 左侧 7.5em；手机 label 在控件上方。说明文字 12px 三级色；错误红字贴字段。
加载中 / 空结果 / 尚未执行 / 部分失败 / 请求错误分开表达：`PageBusy`（毛玻璃 + 药片转圈）、`EmptyState`（图标 + 一句为什么 + 一句下一步 + 动作）、`notice`（左侧 3px 色条）。
有后果的操作走 `confirmAction()`（危险操作带图标方块与实心红按钮）。

## 验证

`e2e/redesign-shots.mjs` 一条命令截全部路由（`SHOT_ROUTES` / `SHOT_APPEARANCES` / `SHOT_VIEWPORT=mobile|tablet` / `SHOT_FULLPAGE=1`）。共享控件改动值得检查键盘导航、标签关联、焦点恢复、禁用状态与取消路径；四档外观各看一张、手机各看一张。
