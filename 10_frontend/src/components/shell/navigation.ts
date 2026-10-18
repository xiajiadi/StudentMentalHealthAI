import { Activity, BookOpenCheck, ChartNoAxesCombined, ClipboardList, FileCheck2, History, LayoutDashboard, Settings2, ShieldCheck, UsersRound } from '@lucide/vue'
import { defineComponent, h } from 'vue'
import type { Component } from 'vue'
import type { Role } from '@/types/contracts'

export interface WorkspaceNavItem { label: string; to: string; icon: Component }
export interface WorkspaceConfig { title: string; home: string; items: WorkspaceNavItem[] }

const createAcademyIcon = (name: string, path: string, evenOdd = false) => defineComponent({
  name,
  props: { size: { type: Number, default: 18 } },
  setup(props, { attrs }) {
    return () => h('svg', {
      ...attrs,
      width: props.size,
      height: props.size,
      viewBox: '0 0 32 32',
      fill: 'none',
      xmlns: 'http://www.w3.org/2000/svg',
      focusable: 'false',
    }, [h('path', {
      d: path,
      fill: 'currentColor',
      ...(evenOdd ? { fillRule: 'evenodd', clipRule: 'evenodd' } : {}),
    })])
  },
})

export const AcademyEducationIcon = createAcademyIcon('AcademyEducationIcon', 'M28.2731 20.6362C28.8756 20.6362 29.364 21.1246 29.364 21.7271V28.2726C29.364 28.8751 28.8756 29.3635 28.2731 29.3635H8.63672C8.03423 29.3635 7.54581 28.8751 7.54581 28.2726V21.7271C7.54581 21.1246 8.03423 20.6362 8.63672 20.6362H28.2731ZM24.4549 27.1817H27.1822V22.818H24.4549V27.1817ZM9.72763 27.1817H22.2731V22.818H9.72763V27.1817ZM23.364 12.4544C23.9665 12.4544 24.4549 12.9428 24.4549 13.5453V18.4544C24.4549 19.0569 23.9665 19.5453 23.364 19.5453H3.72763C3.12514 19.5453 2.63672 19.0569 2.63672 18.4544V13.5453C2.63672 12.9428 3.12514 12.4544 3.72763 12.4544H23.364ZM19.5458 17.3635H22.2731V14.6362H19.5458V17.3635ZM4.81854 17.3635H17.364V14.6362H4.81854V17.3635ZM28.2731 2.63623C28.8756 2.63623 29.364 3.12465 29.364 3.72714V10.2726C29.364 10.8751 28.8756 11.3635 28.2731 11.3635H8.63672C8.03423 11.3635 7.54581 10.8751 7.54581 10.2726V3.72714C7.54581 3.12465 8.03423 2.63623 8.63672 2.63623H28.2731ZM24.4549 9.18168H27.1822V4.81805H24.4549V9.18168ZM9.72763 9.18168H22.2731V4.81805H9.72763V9.18168Z')

export const workspaceConfig: Partial<Record<Role, WorkspaceConfig>> = {
  student: { title: 'Student Workspace', home: '/student/home', items: [
    { label: '首页', to: '/student/home', icon: LayoutDashboard },
    { label: '我的测评', to: '/student/assessments', icon: ClipboardList },
    { label: '测评反馈', to: '/student/feedback', icon: FileCheck2 },
    { label: '教育支持', to: '/student/support', icon: AcademyEducationIcon },
    { label: '我的记录', to: '/student/history', icon: History },
  ] },
  teacher: { title: 'Teacher Workspace', home: '/teacher/overview', items: [
    { label: '工作概览', to: '/teacher/overview', icon: LayoutDashboard },
    { label: '班级进度', to: '/teacher/classes', icon: UsersRound },
    { label: '测评任务', to: '/teacher/tasks', icon: ClipboardList },
    { label: '数据分析', to: '/teacher/analytics', icon: ChartNoAxesCombined },
  ] },
  psychological_specialist: { title: 'Counselor Workspace', home: '/specialist/overview', items: [
    { label: '工作概览', to: '/specialist/overview', icon: LayoutDashboard },
    { label: '专业资料', to: '/specialist/resources', icon: BookOpenCheck },
    { label: 'CAT 管理', to: '/specialist/cat', icon: Activity },
    { label: '工作事项', to: '/specialist/tasks', icon: FileCheck2 },
  ] },
  school_admin: { title: 'Admin Workspace', home: '/admin/overview', items: [
    { label: '管理概览', to: '/admin/overview', icon: LayoutDashboard },
    { label: '用户与角色', to: '/admin/users', icon: UsersRound },
    { label: '运营记录', to: '/admin/audit', icon: ClipboardList },
    { label: '系统设置', to: '/admin/settings', icon: Settings2 },
  ] },
  reviewer: { title: 'Safety Review Workspace', home: '/reviewer/queue', items: [
    { label: '复核队列', to: '/reviewer/queue', icon: ShieldCheck },
  ] },
}

export const roleHomes = Object.fromEntries(Object.entries(workspaceConfig).map(([role, config]) => [role, config?.home])) as Record<Role, string>
export const roleLabels: Record<Role, string> = {
  student: '学生', teacher: '教师', psychological_specialist: '心理专业人员', school_admin: '学校管理员', reviewer: '安全复核员',
}
