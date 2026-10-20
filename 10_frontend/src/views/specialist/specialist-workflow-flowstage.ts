import type { Component } from 'vue'
import {
  BookOpenCheck,
  ClipboardCheck,
  Layers,
  MessageSquareText,
  ShieldCheck,
} from '@lucide/vue'

export type SpecialistWorkflowKey =
  | 'task-reviews'
  | 'research-feedback'
  | 'education-review'
  | 'research-candidates'
  | 'assigned-safety'

export type SpecialistWorkflowTone = 'cyan' | 'violet' | 'mint' | 'purple' | 'amber'

export type SpecialistFlowstageListState = 'idle' | 'loading' | 'ready' | 'error'

export type SpecialistFlowstageItem = Readonly<{
  key: string
  label: string
  status?: string
  meta?: string
}>

export type SpecialistFlowstageBridge = Readonly<{
  flowstageItems: readonly SpecialistFlowstageItem[]
  flowstageState: SpecialistFlowstageListState
  flowstageCountLabel: string
  flowstageEmptyMessage: string
  flowstageSelectedKey: string
  selectFlowstageItem: (key: string) => void | Promise<void>
}>

export type SpecialistWorkflowDefinition = Readonly<{
  key: SpecialistWorkflowKey
  label: string
  english: string
  code: string
  icon: Component
  tone: SpecialistWorkflowTone
  description: string
  scope: string
  areas: readonly string[]
}>

export const specialistWorkflowDefinitions: readonly SpecialistWorkflowDefinition[] = [
  {
    key: 'task-reviews',
    label: '任务复核',
    english: 'REVIEW',
    code: '01',
    icon: ClipboardCheck,
    tone: 'cyan',
    description: '查看服务端指派任务内的完成记录，并沿用现有流程提交专业复核。',
    scope: '列表由服务端按本校心理专业人员角色及任务指派范围返回。',
    areas: ['任务列表', '完成记录', '复核案例'],
  },
  {
    key: 'research-feedback',
    label: '研究反馈',
    english: 'FEEDBACK',
    code: '02',
    icon: MessageSquareText,
    tone: 'violet',
    description: '审阅研究工作范围内的记录，并独立管理教育反馈版本。',
    scope: '研究任务、完成会话和反馈记录沿用各自的服务端授权与状态。',
    areas: ['研究任务', '复核案例', '反馈版本'],
  },
  {
    key: 'education-review',
    label: '教育审核',
    english: 'EDUCATION',
    code: '03',
    icon: BookOpenCheck,
    tone: 'mint',
    description: '核查经分享的教育内容与引用，并维护现有修订和发布状态。',
    scope: '仅处理服务端返回的可访问分享内容；发布与撤回继续使用原有流程。',
    areas: ['分享内容', '来源引用', '修订草稿'],
  },
  {
    key: 'research-candidates',
    label: '研究候选',
    english: 'CANDIDATES',
    code: '04',
    icon: Layers,
    tone: 'purple',
    description: '查看研究模拟候选及其来源，操作仍遵循候选的原有生命周期。',
    scope: '候选仅作授权教职工研究参考，不代表批准或学生可见反馈。',
    areas: ['研究任务', '参考候选', '生成任务'],
  },
  {
    key: 'assigned-safety',
    label: '安全事项',
    english: 'SAFETY',
    code: '05',
    icon: ShieldCheck,
    tone: 'amber',
    description: '处理当前账号已被指派的安全事项，并保留现有安全提示状态。',
    scope: '仅显示服务端当前已指派事项；关闭复核流程不代表解除安全提示。',
    areas: ['已指派事项', '复核备注', '流程状态'],
  },
] as const

const specialistWorkflowKeys = new Set<string>(specialistWorkflowDefinitions.map((item) => item.key))

export function isSpecialistWorkflowKey(value: unknown): value is SpecialistWorkflowKey {
  return typeof value === 'string' && specialistWorkflowKeys.has(value)
}
