import { computed, defineComponent, h, inject, provide, ref, watch, type ComputedRef, type InjectionKey, type PropType } from 'vue'
import { RouterLink } from 'vue-router'
import { ChevronDown } from '@lucide/vue'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '../collapsible'

const navKey: InjectionKey<{ active: ComputedRef<string>; collapsed: ComputedRef<boolean>; router: ComputedRef<boolean>; open: ComputedRef<string[]> }> = Symbol('navigation')
export const NavMenu = defineComponent({
  name: 'NavMenu', props: { defaultActive: { type: String, default: '' }, defaultOpeneds: { type: Array as PropType<string[]>, default: () => [] }, collapse: Boolean, collapseTransition: Boolean, router: Boolean },
  setup(props, { slots }) {
    provide(navKey, { active: computed(() => props.defaultActive), collapsed: computed(() => props.collapse), router: computed(() => props.router), open: computed(() => props.defaultOpeneds) })
    return () => h('nav', { class: ['nav-menu', { 'nav-menu--collapsed': props.collapse }], 'aria-label': '导航' }, slots.default?.())
  },
})
export const NavItem = defineComponent({
  name: 'NavItem', props: { index: { type: String, default: '' }, disabled: Boolean },
  setup(props, { slots }) {
    const nav = inject(navKey, undefined)
    return () => {
      const attrs = { class: ['nav-item', { 'is-active': nav?.active.value === props.index }], 'aria-current': nav?.active.value === props.index ? 'page' as const : undefined }
      const content = () => [slots.default?.(), slots.title ? h('span', { class: 'nav-item__label' }, slots.title()) : null]
      return nav?.router.value && !props.disabled ? h(RouterLink, { ...attrs, to: props.index }, content)
        : h('button', { ...attrs, type: 'button', disabled: props.disabled }, content())
    }
  },
})
export const NavGroup = defineComponent({
  name: 'NavGroup', props: { index: { type: String, default: '' } },
  setup(props, { slots }) {
    const nav = inject(navKey, undefined)
    const open = ref(nav?.open.value.includes(props.index) ?? true)
    watch(() => nav?.active.value, value => { if (value?.startsWith(props.index)) open.value = true })
    return () => h(Collapsible, { open: open.value, 'onUpdate:open': (value: boolean) => { open.value = value }, class: 'nav-group' }, () => [
      h(CollapsibleTrigger, { class: 'nav-group__trigger' }, () => [slots.title?.(), h(ChevronDown, { class: ['nav-group__chevron size-3.5', { 'rotate-180': open.value }], 'aria-hidden': true })]),
      h(CollapsibleContent, { class: 'nav-group__content' }, slots.default),
    ])
  },
})
