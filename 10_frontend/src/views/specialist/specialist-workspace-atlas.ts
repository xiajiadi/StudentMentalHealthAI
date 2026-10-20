import type { Component } from 'vue'
import type { RouteLocationRaw } from 'vue-router'
import {
  BookMarked,
  BookOpenCheck,
  ClipboardCheck,
  FlaskConical,
  Layers,
  MessageSquareText,
  Network,
  ShieldCheck,
} from '@lucide/vue'

export type SpecialistAtlasFocus =
  | 'task-reviews'
  | 'research-feedback'
  | 'education-review'
  | 'research-candidates'
  | 'assigned-safety'
  | 'simulation'
  | 'research-management'

export type SpecialistAtlasAccent = 'cyan' | 'violet' | 'lavender' | 'sky' | 'amber' | 'mint' | 'teal'
export type SpecialistAtlasGroupId = 'review' | 'content' | 'system'

export type SpecialistAtlasEntry = {
  id: SpecialistAtlasFocus | 'resources'
  title: string
  group: SpecialistAtlasGroupId
  groupLabel: string
  summary: string
  description: string
  icon: Component
  accent: SpecialistAtlasAccent
  to: RouteLocationRaw
  focus?: SpecialistAtlasFocus
}

export const specialistAtlasGroups: Array<{
  id: SpecialistAtlasGroupId
  title: string
  code: string
}> = [
  { id: 'review', title: '专业复核', code: '01 / REVIEW' },
  { id: 'content', title: '教育研究', code: '02 / CONTENT' },
  { id: 'system', title: '安全与工程', code: '03 / SYSTEM' },
]

const taskTarget = (focus: SpecialistAtlasFocus): RouteLocationRaw => ({
  path: '/specialist/tasks',
  query: { focus },
})

const catTarget = (focus: SpecialistAtlasFocus): RouteLocationRaw => ({
  path: '/specialist/cat',
  query: { focus },
})

export const specialistAtlasEntries: SpecialistAtlasEntry[] = [
  {
    id: 'task-reviews',
    title: '任务复核',
    group: 'review',
    groupLabel: '专业复核',
    summary: '受控审核',
    description: '查看服务端指派给当前账号的专业任务复核。',
    icon: ClipboardCheck,
    accent: 'cyan',
    focus: 'task-reviews',
    to: taskTarget('task-reviews'),
  },
  {
    id: 'research-feedback',
    title: '研究反馈',
    group: 'review',
    groupLabel: '专业复核',
    summary: '意见记录',
    description: '进入研究反馈工作流，查看并记录当前可处理的意见。',
    icon: MessageSquareText,
    accent: 'violet',
    focus: 'research-feedback',
    to: taskTarget('research-feedback'),
  },
  {
    id: 'education-review',
    title: '教育审核',
    group: 'content',
    groupLabel: '教育研究',
    summary: '独立内容',
    description: '审核独立教育内容，沿用现有流程与服务端状态。',
    icon: BookOpenCheck,
    accent: 'lavender',
    focus: 'education-review',
    to: taskTarget('education-review'),
  },
  {
    id: 'research-candidates',
    title: '研究候选',
    group: 'content',
    groupLabel: '教育研究',
    summary: '候选方案',
    description: '查看研究项目候选项并进入既有审核工作流。',
    icon: Layers,
    accent: 'sky',
    focus: 'research-candidates',
    to: taskTarget('research-candidates'),
  },
  {
    id: 'resources',
    title: '专业资料',
    group: 'content',
    groupLabel: '教育研究',
    summary: '来源目录',
    description: '查阅研究教育来源目录中的公开元数据与权利记录。',
    icon: BookMarked,
    accent: 'cyan',
    to: { path: '/specialist/resources' },
  },
  {
    id: 'assigned-safety',
    title: '安全事项',
    group: 'system',
    groupLabel: '安全与工程',
    summary: '仅已指派',
    description: '仅处理服务端指派给当前账号的安全事项。',
    icon: ShieldCheck,
    accent: 'amber',
    focus: 'assigned-safety',
    to: taskTarget('assigned-safety'),
  },
  {
    id: 'simulation',
    title: 'CAT 模拟',
    group: 'system',
    groupLabel: '安全与工程',
    summary: '工程实验',
    description: '进入 CAT 工程模拟区域；工程模拟不代表测量学验证。',
    icon: FlaskConical,
    accent: 'mint',
    focus: 'simulation',
    to: catTarget('simulation'),
  },
  {
    id: 'research-management',
    title: '研究管理',
    group: 'system',
    groupLabel: '安全与工程',
    summary: '方案管理',
    description: '查看研究方案管理区域并遵循其既有权限边界。',
    icon: Network,
    accent: 'teal',
    focus: 'research-management',
    to: catTarget('research-management'),
  },
]
