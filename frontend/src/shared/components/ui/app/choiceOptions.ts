import type { VNode, VNodeChild } from 'vue'
import { componentName, flattenNodes, nodeSlot } from './vnodeContent'

export interface ChoiceEntry { value: unknown; label: string; disabled?: boolean; group?: string; render?: () => VNodeChild }
export function collectChoices(nodes: VNode[], group?: string): ChoiceEntry[] {
  return flattenNodes(nodes).flatMap(node => {
    const name = componentName(node)
    if (name === 'ChoiceGroup') {
      return collectChoices(flattenNodes(nodeSlot(node)?.()), String(node.props?.label ?? ''))
    }
    const props = (node.props ?? {}) as Record<string, unknown>
    const isOption = name === 'ChoiceOption' || ('value' in props || 'label' in props)
    if (!isOption) return []
    return [{ value: props.value, label: String(props.label ?? props.value ?? ''), disabled: props.disabled === '' || Boolean(props.disabled), group, render: nodeSlot(node) }]
  })
}
