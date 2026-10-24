import { Building2, ClipboardList, Server, UsersRound } from '@lucide/vue'
import type { Component } from 'vue'

export type AdminFolderId = 'classes' | 'accounts' | 'operations' | 'system'
export type AdminFolderTone = 'aqua' | 'lavender' | 'sage' | 'sand'

export interface AdminWorkspaceAction {
  id: string
  label: string
  description: string
  group: string
  to: string
  keywords: string[]
}

export interface AdminWorkspaceFolder {
  id: AdminFolderId
  title: string
  description: string
  category: string
  icon: Component
  tone: AdminFolderTone
  actionIds: string[]
}

export const adminWorkspaceFolders: AdminWorkspaceFolder[] = [
  {
    id: 'classes',
    title: '班级管理',
    description: '班级数量与成员构成。',
    category: '组织目录',
    icon: Building2,
    tone: 'aqua',
    actionIds: ['admin-class-management', 'admin-create-class', 'admin-class-assignment'],
  },
  {
    id: 'accounts',
    title: '账号管理',
    description: '学生与教师账号概况。',
    category: '账号目录',
    icon: UsersRound,
    tone: 'lavender',
    actionIds: ['admin-accounts', 'admin-import-accounts', 'admin-activate-accounts'],
  },
  {
    id: 'operations',
    title: '任务运营事务',
    description: '任务发布与本校运营记录。',
    category: '任务与记录',
    icon: ClipboardList,
    tone: 'sage',
    actionIds: ['admin-publish-task', 'admin-research-tasks', 'admin-audit'],
  },
  {
    id: 'system',
    title: '系统状态',
    description: '依赖服务运行状态。',
    category: '只读状态',
    icon: Server,
    tone: 'sand',
    actionIds: ['admin-system-health'],
  },
]

export const adminWorkspaceActions: AdminWorkspaceAction[] = [
  {
    id: 'admin-class-management',
    label: '打开班级管理',
    description: '查看本校班级与成员分配。',
    group: '班级管理',
    to: '/admin/users?directoryView=classes',
    keywords: ['班级', '组织', '学生', '教师', '成员分配'],
  },
  {
    id: 'admin-create-class',
    label: '创建班级',
    description: '进入班级视图并创建班级。',
    group: '班级管理',
    to: '/admin/users?directoryAction=create-class',
    keywords: ['班级', '新建班级', '组织'],
  },
  {
    id: 'admin-class-assignment',
    label: '管理班级人员',
    description: '打开班级视图并选择班级。',
    group: '班级管理',
    to: '/admin/users?directoryAction=manage-class-people',
    keywords: ['班级', '学生', '教师', '分配', '人员'],
  },
  {
    id: 'admin-accounts',
    label: '打开账号管理',
    description: '查看本校学生、教师账号与批次。',
    group: '账号管理',
    to: '/admin/users',
    keywords: ['账号', '导入', '批量导入', '激活', '学生', '教师'],
  },
  {
    id: 'admin-import-accounts',
    label: '导入账号',
    description: '通过 CSV 导入本校账号。',
    group: '账号管理',
    to: '/admin/users?directoryAction=import-accounts',
    keywords: ['账号', 'CSV', '批量导入', '学生', '教师'],
  },
  {
    id: 'admin-activate-accounts',
    label: '批量发行一次性凭据',
    description: '为待首次登录账号批量发行凭据。',
    group: '账号管理',
    to: '/admin/users?directoryAction=issue-credentials',
    keywords: ['账号', '待首次登录', '一次性凭据', '批量发行', '学生', '教师'],
  },
  {
    id: 'admin-publish-task',
    label: '发布测评任务',
    description: '打开现有任务发布和人员分配流程。',
    group: '任务运营事务',
    to: '/admin/overview#admin-school-operations',
    keywords: ['测评', '任务', '创建任务', '新建任务', '发布', '专业人员', '分配'],
  },
  {
    id: 'admin-research-tasks',
    label: '研究任务管理',
    description: '打开现有研究班级任务管理。',
    group: '任务运营事务',
    to: '/admin/overview#admin-research-management',
    keywords: ['研究', '研究班级', '公开资料', '仿真'],
  },
  {
    id: 'admin-audit',
    label: '查看本校操作记录',
    description: '进入本校运营记录。',
    group: '任务运营事务',
    to: '/admin/audit',
    keywords: ['运营', '操作记录', '审计', '操作历史', '本校记录'],
  },
  {
    id: 'admin-system-health',
    label: '查看服务状态',
    description: '查看只读依赖健康信息。',
    group: '系统状态',
    to: '/admin/settings',
    keywords: ['系统', '服务', '依赖', '健康', '状态'],
  },
]

export const getFolderActions = (folder: AdminWorkspaceFolder | null) =>
  folder ? folder.actionIds.map((id) => adminWorkspaceActions.find((action) => action.id === id)).filter((action): action is AdminWorkspaceAction => Boolean(action)) : []
