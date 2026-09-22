/**
 * 策略域的标签底色：把旧 `UiBadge` 的语义色调翻成 shadcn `Badge` 的类名。
 *
 * shadcn 的 `Badge` 只有 default / secondary / destructive / outline 四档，
 * 而策略页用到了 ok / warn / info / stamp 这些状态语义（红绿只留给价格）。
 * 形状与内边距交给 `Badge` 原语，颜色按本仓既有语义类补上——与
 * `features/ops/components/PaperRoleReviewPanel.vue` 的 `ROLE_BADGE` 是同一套写法。
 */
export type StrategyBadgeTone =
  | 'default'
  | 'secondary'
  | 'outline'
  | 'up'
  | 'down'
  | 'warn'
  | 'info'
  | 'ok'
  | 'stamp'

const TONE_CLASS: Record<StrategyBadgeTone, string> = {
  default: 'border-seal-border bg-seal-soft text-seal-ink',
  secondary: 'border-line bg-sunken text-mist',
  outline: 'border-line-default bg-surface text-mist',
  up: 'border-transparent bg-up-soft text-up',
  down: 'border-transparent bg-down-soft text-down',
  warn: 'border-transparent bg-warn-soft text-warn-ink',
  info: 'border-transparent bg-info-soft text-info-ink',
  ok: 'border-transparent bg-ok-soft text-ok',
  stamp: 'border-stamp/40 bg-surface text-stamp',
}

export function badgeTone(tone?: string | null): string {
  return TONE_CLASS[tone as StrategyBadgeTone] ?? TONE_CLASS.default
}
