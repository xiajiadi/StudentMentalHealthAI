import type { SchoolOperationsAuditCategory, SchoolOperationsAuditEvent } from '@/api/client'

export const auditCategoryLabel: Record<SchoolOperationsAuditCategory, string> = {
  organization: '学校', class: '班级', member: '成员',
  account_batch: '账号批次', account: '账号', task: '任务',
}

export const auditActionLabel: Record<SchoolOperationsAuditEvent['action'], string> = {
  'school_directory.rename_school': '调整学校名称',
  'school_directory.rename_class': '调整班级名称',
  'school_directory.rename_member': '调整成员名称',
  'school_directory.import_accounts': '导入账号批次',
  'school_directory.activate_account': '激活账号',
  'school_tasks.task.published': '发布测评任务',
}

export const auditResultLabel: Record<SchoolOperationsAuditEvent['result'], string> = {
  SUCCESS: '成功', FAILURE: '失败', DENIED: '未获授权',
}

export const dependencyNames: Record<string, string> = {
  cat: 'CAT 测评',
  rag: 'RAG 检索',
  llm_runtime: 'LLM 运行时',
  safety: '安全校验',
  post_assessment_worker: '测后处理',
  research_education_worker: '研究教育任务',
  research_programme_worker: '研究项目任务',
  research_general_education_draft_worker: '通用教育草稿',
}

export const dependencyStatusLabels: Record<string, string> = {
  READY: '正常', AVAILABLE: '正常', UNAVAILABLE: '需关注',
  DEFERRED: '未配置', DISABLED: '已关闭', STARTING: '启动中', UNKNOWN: '未知',
}
