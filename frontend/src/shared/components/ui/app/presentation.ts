import { computed, defineComponent, h, inject, provide, ref, type Component, type CSSProperties, type PropType } from 'vue'
import { AlertCircle, CheckCircle, Info, Inbox, TriangleAlert, X } from '@lucide/vue'
import { Alert, AlertDescription, AlertTitle } from '../alert'
import { Badge } from '../badge'
import { Button } from '../button'
import { Card, CardContent, CardHeader } from '../card'
import { Avatar, AvatarFallback, AvatarImage } from '../avatar'
import { Progress } from '../progress'
import { Separator } from '../separator'
import { Skeleton } from '../skeleton'
import { cssLength } from './context'

export const Notice = defineComponent({
  name: 'Notice',
  props: { title: String, description: String, tone: { type: String, default: 'info' }, closable: { type: Boolean, default: true }, showIcon: Boolean },
  emits: ['close'],
  setup(props, { slots, emit }) {
    const visible = ref(true)
    const icons: Record<string, Component> = { success: CheckCircle, warning: TriangleAlert, error: AlertCircle, danger: AlertCircle, info: Info }
    return () => visible.value ? h(Alert, { class: 'notice', 'data-tone': props.tone, role: props.tone === 'error' ? 'alert' : 'status' }, () => [
      props.showIcon ? h(icons[props.tone] ?? Info, { class: 'size-4', 'aria-hidden': true }) : null,
      props.title || slots.title ? h(AlertTitle, {}, slots.title ?? (() => props.title)) : null,
      slots.default || props.description ? h(AlertDescription, {}, slots.default ?? (() => props.description)) : null,
      props.closable ? h('button', { type: 'button', class: 'notice__close field-icon-button', 'aria-label': '关闭提示', onClick: () => { visible.value = false; emit('close') } }, [h(X, { class: 'size-4' })]) : null,
    ]) : null
  },
})

export const StatusBadge = defineComponent({
  name: 'StatusBadge',
  props: { tone: String, closable: Boolean, size: String, effect: String },
  emits: ['close'],
  setup: (props, { slots, emit }) => () => h(Badge, { class: 'status-badge', 'data-tone': props.tone, variant: props.effect === 'dark' ? 'default' : 'outline' }, () => [
    slots.default?.(), props.closable ? h('button', { type: 'button', class: 'field-icon-button', 'aria-label': '移除', onClick: (event: MouseEvent) => { event.stopPropagation(); emit('close', event) } }, [h(X, { class: 'size-3' })]) : null,
  ]),
})

export const EmptyBlock = defineComponent({
  name: 'EmptyBlock',
  props: { description: { type: String, default: '暂无数据' }, imageSize: [String, Number] },
  setup: (props, { slots }) => () => h('div', { class: 'empty-block', role: 'status' }, [
    slots.image?.() ?? h(Inbox, { class: 'empty-block__icon', 'aria-hidden': true }),
    h('p', { class: 'empty-block__description' }, slots.description?.() ?? props.description), slots.default?.(),
  ]),
})

export const IconBox = defineComponent({
  name: 'IconBox', props: { size: [String, Number] },
  setup: (props, { slots }) => () => h('span', { class: 'icon-box', style: props.size ? { fontSize: cssLength(props.size) } : undefined }, slots.default?.()),
})

export const ContextSeparator = defineComponent({
  name: 'ContextSeparator', props: { contentPosition: String, direction: String },
  setup: (props, { slots }) => () => slots.default ? h('div', { class: 'context-separator', 'data-align': props.contentPosition }, [
    h(Separator, { class: 'flex-1' }), h('span', {}, slots.default()), h(Separator, { class: 'flex-1' }),
  ]) : h(Separator, { orientation: props.direction === 'vertical' ? 'vertical' : 'horizontal' }),
})

export const ProgressMeter = defineComponent({
  name: 'ProgressMeter', props: { percentage: Number, showText: { type: Boolean, default: true }, status: String, strokeWidth: Number },
  setup: (props, { slots }) => () => h('div', { class: 'progress-meter', 'data-tone': props.status }, [
    h(Progress, { modelValue: Math.min(100, Math.max(0, props.percentage ?? 0)), style: props.strokeWidth ? { height: cssLength(props.strokeWidth) } : undefined }),
    props.showText ? h('span', { class: 'progress-meter__value' }, slots.default?.() ?? `${Math.round(props.percentage ?? 0)}%`) : null,
  ]),
})

export const SkeletonBlock = defineComponent({
  name: 'SkeletonBlock', props: { rows: { type: Number, default: 3 }, animated: Boolean, loading: { type: Boolean, default: true } },
  setup: (props, { slots }) => () => props.loading ? h('div', { class: 'skeleton-block', role: 'status', 'aria-label': '加载中' },
    slots.template?.() ?? Array.from({ length: Math.max(1, props.rows + 1) }, (_, index) => h(Skeleton, { key: index, class: index === 0 ? 'h-4 w-1/3' : index === props.rows ? 'h-4 w-3/4' : 'h-4 w-full' }))) : slots.default?.(),
})
export const SkeletonShape = defineComponent({
  name: 'SkeletonShape', props: { variant: String },
  setup: props => () => h(Skeleton, { class: ['skeleton-shape', props.variant === 'circle' ? 'rounded-full size-10' : props.variant === 'image' ? 'aspect-video w-full' : 'h-4 w-full'] }),
})

export const CountBadge = defineComponent({
  name: 'CountBadge', props: { hidden: Boolean, isDot: Boolean, value: [String, Number] },
  setup: (props, { slots }) => () => h('span', { class: 'count-badge' }, [slots.default?.(), !props.hidden ? h(Badge, { class: ['count-badge__mark', props.isDot ? 'count-badge__mark--dot' : ''], 'aria-label': props.isDot ? '有新内容' : undefined }, () => props.isDot ? '' : String(props.value ?? '')) : null]),
})
export const SurfaceCard = defineComponent({
  name: 'SurfaceCard', props: { shadow: String },
  setup: (_props, { slots }) => () => h(Card, { class: 'surface-card' }, () => [slots.header ? h(CardHeader, {}, slots.header) : null, h(CardContent, {}, slots.default)]),
})
export const UserAvatar = defineComponent({
  name: 'UserAvatar', props: { src: String, alt: String, size: [String, Number], shape: String },
  setup: (props, { slots }) => () => h(Avatar, { class: props.shape === 'square' ? 'rounded-md' : '', style: typeof props.size === 'number' ? { width: cssLength(props.size), height: cssLength(props.size) } : undefined }, () => [
    props.src ? h(AvatarImage, { src: props.src, alt: props.alt ?? '' }) : null, h(AvatarFallback, {}, slots.default ?? (() => props.alt?.slice(0, 1) || '我')),
  ]),
})
export const ButtonGroup = defineComponent({ name: 'ButtonGroup', setup: (_props, { slots }) => () => h('div', { role: 'group', class: 'button-group' }, slots.default?.()) })

export const ScrollContainer = defineComponent({
  name: 'ScrollContainer', props: { height: [String, Number], maxHeight: [String, Number] },
  setup(props, { slots, expose }) {
    const viewport = ref<HTMLElement>()
    expose({ wrapRef: viewport, scrollTo: (options: ScrollToOptions) => viewport.value?.scrollTo(options), setScrollTop: (value: number) => { if (viewport.value) viewport.value.scrollTop = value }, update: () => undefined })
    return () => h('div', { ref: viewport, class: 'scroll-container', style: { height: cssLength(props.height), maxHeight: cssLength(props.maxHeight) } }, slots.default?.())
  },
})

export const GridRow = defineComponent({
  name: 'GridRow', props: { gutter: Number },
  setup: (props, { slots }) => () => h('div', { class: 'grid-row', style: { gap: cssLength(props.gutter, '1rem') } }, slots.default?.()),
})
export const GridColumn = defineComponent({
  name: 'GridColumn', props: { span: { type: Number, default: 24 }, xs: Number, sm: Number, md: Number, lg: Number, xl: Number },
  setup: (props, { slots }) => () => h('div', { class: 'grid-column', style: {
    '--span': props.span, '--span-xs': props.xs ?? props.span, '--span-sm': props.sm ?? props.xs ?? props.span,
    '--span-md': props.md ?? props.sm ?? props.xs ?? props.span, '--span-lg': props.lg ?? props.md ?? props.sm ?? props.span,
    '--span-xl': props.xl ?? props.lg ?? props.md ?? props.sm ?? props.span,
  } as CSSProperties }, slots.default?.()),
})
export const DetailList = defineComponent({
  name: 'DetailList', props: { column: { type: Number, default: 3 }, border: Boolean, size: String, labelWidth: [String, Number] },
  setup(props, { slots }) {
    provide('detail-columns', computed(() => props.column))
    return () => h('dl', { class: ['detail-list', { 'detail-list--bordered': props.border }], style: { '--detail-columns': props.column, '--detail-label-width': cssLength(props.labelWidth) } as CSSProperties }, slots.default?.())
  },
})
export const DetailItem = defineComponent({
  name: 'DetailItem', props: { label: String, span: { type: Number, default: 1 } },
  setup(props, { slots }) {
    const columns = inject('detail-columns', computed(() => 3))
    return () => h('div', { class: 'detail-item', style: { gridColumn: `span ${Math.min(props.span, columns.value)}` } }, [
      h('dt', { class: 'detail-item__label' }, slots.label?.() ?? props.label), h('dd', { class: 'detail-item__content' }, slots.default?.()),
    ])
  },
})
export const ActionLink = defineComponent({
  name: 'ActionLink', props: { href: String, tone: String, disabled: Boolean, icon: [Object, Function] as PropType<Component> },
  setup: (props, { slots }) => () => h(Button, { as: props.href ? 'a' : 'button', href: props.href, type: props.href ? undefined : 'button', variant: 'link', disabled: props.disabled, class: 'action-link', 'data-tone': props.tone }, () => [props.icon ? h(props.icon, { class: 'size-4' }) : null, slots.default?.()]),
})
