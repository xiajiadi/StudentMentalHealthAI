import { BookOpenCheck, ClipboardList, FileCheck2, LayoutDashboard, LifeBuoy, Settings2, ShieldCheck, UsersRound } from '@lucide/vue'
import type { Component } from 'vue'
import type { Role } from '@/types/contracts'

export interface WorkspaceNavItem { label: string; to: string; icon: Component }
export interface WorkspaceConfig { title: string; home: string; items: WorkspaceNavItem[] }

export const workspaceConfig: Partial<Record<Role, WorkspaceConfig>> = {
  student: { title: '学生空间', home: '/student/home', items: [
    { label: '我的首页', to: '/student/home', icon: LayoutDashboard },
    { label: '测评记录', to: '/student/history', icon: ClipboardList },
    { label: '支持对话', to: '/student/support', icon: LifeBuoy },
  ] },
  teacher: { title: '教师空间', home: '/teacher/overview', items: [
    { label: '工作概览', to: '/teacher/overview', icon: LayoutDashboard },
    { label: '学生支持', to: '/teacher/students', icon: UsersRound },
  ] },
  psychological_specialist: { title: '心理专业工作区', home: '/specialist/overview', items: [
    { label: '工作概览', to: '/specialist/overview', icon: LayoutDashboard },
    { label: '专业资料', to: '/specialist/resources', icon: BookOpenCheck },
    { label: '工作事项', to: '/specialist/tasks', icon: FileCheck2 },
  ] },
  school_admin: { title: '学校管理空间', home: '/admin/overview', items: [
    { label: '管理概览', to: '/admin/overview', icon: LayoutDashboard },
    { label: '用户与角色', to: '/admin/users', icon: UsersRound },
    { label: '系统设置', to: '/admin/settings', icon: Settings2 },
  ] },
  reviewer: { title: '安全复核空间', home: '/reviewer/queue', items: [
    { label: '复核队列', to: '/reviewer/queue', icon: ShieldCheck },
  ] },
}

export const roleHomes = Object.fromEntries(Object.entries(workspaceConfig).map(([role, config]) => [role, config?.home])) as Record<Role, string>
export const roleLabels: Record<Role, string> = {
  student: '学生', teacher: '教师', psychological_specialist: '心理专业人员', school_admin: '学校管理员', reviewer: '安全复核员',
}
