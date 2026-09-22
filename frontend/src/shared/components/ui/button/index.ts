import type { VariantProps } from "class-variance-authority"
import { cva } from "class-variance-authority"

export { default as Button } from "./Button.vue"

/*
 * 按钮体系（参考 Vercel / Linear）：
 * - default：实心主色 + 1px 内高光 + 极淡投影，按下时压暗。一页只放一颗。
 * - outline：白底 hairline，悬停底色抬一档；次要操作默认用它。
 * - secondary：下沉底无边，工具行里的「不抢眼」操作。
 * - ghost：完全透明，图标按钮 / 表格行操作。
 * - destructive：印章红实心；soft-destructive：红字浅底，放在弹窗左侧的破坏性操作。
 * - link：行内文字链接。
 * 尺寸：default 32 / sm 28 / xs 24 / lg 36；icon-* 同高正方形。
 */
export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md text-ui font-medium transition-[color,background-color,border-color,box-shadow,transform] duration-150 select-none disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 shrink-0 [&_svg]:shrink-0 outline-none focus-visible:ring-3 focus-visible:ring-ring/35 focus-visible:border-ring aria-invalid:ring-destructive/20 aria-invalid:border-destructive active:translate-y-px",
  {
    variants: {
      variant: {
        default:
   "bg-primary text-primary-foreground shadow-[var(--shadow-inset-highlight),var(--shadow-xs)] hover:bg-seal-hover active:bg-seal-active",
        destructive:
          "bg-destructive text-white shadow-[var(--shadow-inset-highlight),var(--shadow-xs)] hover:bg-destructive/90 focus-visible:ring-destructive/25",
        "soft-destructive":
          "bg-stamp-soft text-stamp hover:bg-stamp/15 focus-visible:ring-destructive/25",
        outline:
   "border border-line-default bg-surface text-ink shadow-xs hover:bg-hover hover:border-line-strong",
        secondary:
   "bg-sunken text-ink-2 hover:bg-active hover:text-ink",
        ghost:
   "text-ink-2 hover:bg-hover hover:text-ink",
        link: "text-seal-ink underline-offset-4 hover:underline",
      },
      size: {
        "default": "h-[var(--ctl-h)] px-3 has-[>svg]:px-2.5",
        "xs": "h-6 gap-1 rounded-sm px-2 text-aux has-[>svg]:px-1.5 [&_svg:not([class*='size-'])]:size-3",
        "sm": "h-[var(--ctl-h-sm)] gap-1.5 px-2.5 text-aux has-[>svg]:px-2 [&_svg:not([class*='size-'])]:size-3.5",
        "lg": "h-[var(--ctl-h-lg)] rounded-md px-4 text-body has-[>svg]:px-3.5",
        "icon": "size-[var(--ctl-h)]",
 "icon-xs": "size-6 rounded-sm [&_svg:not([class*='size-'])]:size-3.5",
 "icon-sm": "size-[var(--ctl-h-sm)] [&_svg:not([class*='size-'])]:size-4",
        "icon-lg": "size-[var(--ctl-h-lg)]",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
)
export type ButtonVariants = VariantProps<typeof buttonVariants>
