export type Bank = {
  id: string
  name: string
  status: 'draft' | 'published'
  version: number
  item_count: number
  items?: { id: string; stem: string; model: string; content: string }[]
}

export type DesignConfig = {
  name: string
  min_items: number
  max_items: number
  se_target: number
  prior_mean: number
  prior_sd: number
  selection: string
  top_k: number
  seed: number
  content_min: Record<string, number>
}

export type Design = { id: string; bank_id: string; status: 'draft' | 'published'; config: DesignConfig }
export type Session = {
  id: string
  design_id: string
  revision: number
  status: 'active' | 'paused' | 'completed'
  next_item: { id: string; stem: string; options: string[] } | null
  theta: number
  se: number
  stop_reason: string | null
  trace: { index: number; item_id: string; score: number; theta: number; se: number }[]
}
export type Experiment = {
  id: string
  bank_id: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  error?: string
  result?: {
    schemes: {
      name: string
      metrics: Record<string, number>
      conditional: { low: number; high: number; n: number; rmse: number }[]
      exposure: { item_id: string; rate: number }[]
    }[]
  }
}
export type Curves = { theta: number[]; iif: number[]; tif: number[]; probabilities: number[][] }

const root = '/api/v1/school/cat-management/workbench'

export async function catRequest<T>(path: string, payload?: unknown): Promise<T> {
  if (payload === undefined) {
    const response = await fetch(root + path, { credentials: 'same-origin', cache: 'no-store' })
    return decode<T>(response)
  }
  const csrf = await fetch('/api/v1/auth/csrf', { credentials: 'same-origin', cache: 'no-store' })
  const token = csrf.ok ? (await csrf.json()).data?.csrf_token : undefined
  if (typeof token !== 'string' || !token) throw new Error('登录状态已过期，请重新登录。')
  return decode<T>(await fetch(root + path, {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': token },
    body: JSON.stringify(payload),
  }))
}

async function decode<T>(response: Response): Promise<T> {
  const data = await response.json().catch(() => null)
  if (response.ok && data) return data as T
  if (response.status === 401) throw new Error('登录状态已过期，请重新登录。')
  if (response.status === 403) throw new Error('当前身份无法操作此项目。')
  if (response.status === 503) throw new Error('CAT 工作台暂时不可用，请稍后重试。')
  throw new Error(typeof data?.error?.message === 'string' ? data.error.message : '操作未完成，请核对输入后重试。')
}

export function catExport(path: string) {
  return root + path
}
