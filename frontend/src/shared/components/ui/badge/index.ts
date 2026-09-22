import type { VariantProps } from "class-variance-authority"
import { cva } from "class-variance-authority"

export { default as Badge } from "./Badge.vue"

/*
 * 徽标：药片形、11px、中等字重。语义变体一律「浅底 + 深字」，实心只留给 default（主色）。
 * `dot` 变体在左侧带一颗状态点，用于「运行中 / 已停用」这类状态标签。
 */
export const badgeVariants = cva(
  "inline-flex w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-full border px-2 py-0.5 text-kicker font-medium leading-[1.5] whitespace-nowrap transition-[color,box-shadow] [&>svg]:pointer-events-none [&>svg]:size-3 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40 aria-invalid:border-destructive aria-invalid:ring-destructive/20",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground [a&]:hover:bg-primary/90",
        secondary: "border-transparent bg-sunken text-ink-2 [a&]:hover:bg-active",
 outline: "border-line-default bg-surface text-ink-2 [a&]:hover:bg-hover",
        destructive: "border-transparent bg-stamp-soft text-stamp [a&]:hover:bg-stamp/15",
        soft: "border-transparent bg-seal-soft text-seal-ink",
 up: "border-transparent bg-up-soft text-up font-mono tabular-nums",
        down: "border-transparent bg-down-soft text-down font-mono tabular-nums",
        warn: "border-transparent bg-warn-soft text-warn-ink",
 info: "border-transparent bg-info-soft text-info-ink",
        ok: "border-transparent bg-ok-soft text-ok",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
)
export type BadgeVariants = VariantProps<typeof badgeVariants>
