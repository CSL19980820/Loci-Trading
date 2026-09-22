import { Comment, Fragment, createTextVNode, defineComponent, isVNode, type PropType, type VNode, type VNodeChild } from 'vue'

export function flattenNodes(children: unknown): VNode[] {
  if (Array.isArray(children)) return children.flatMap(flattenNodes)
  if (!isVNode(children) || children.type === Comment) return []
  return children.type === Fragment ? flattenNodes(children.children) : [children]
}
export function nodeSlot(node: VNode, name = 'default'): (() => VNodeChild) | undefined {
  const children = node.children
  if (children && !Array.isArray(children) && typeof children === 'object') {
    const slot = children[name]
    if (typeof slot === 'function') return slot as () => VNodeChild
  }
  if (name === 'default' && Array.isArray(children)) return () => children
  if (name === 'default' && typeof children === 'string') return () => createTextVNode(children)
  return undefined
}
export function componentName(node: VNode): string {
  if (typeof node.type !== 'object') return String(node.type)
  const type = node.type as { name?: string; __name?: string }
  return type.name || type.__name || ''
}
export const VNodeContent = defineComponent({
  name: 'VNodeContent',
  props: { render: Function as PropType<() => VNodeChild> },
  setup: props => () => props.render?.(),
})
