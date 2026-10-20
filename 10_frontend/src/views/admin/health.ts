import { createClient, createConfig } from '@/api/generated/client'
import { healthDependencies } from '@/api/generated/sdk.gen'
import type { DependencyStatusDto } from '@/api/generated/types.gen'

const healthClient = createClient(createConfig({
  baseUrl: import.meta.env.VITE_API_BASE_URL || '/',
  credentials: 'include',
}))

export async function readDependencyHealth(): Promise<Record<string, DependencyStatusDto>> {
  const response = await healthDependencies({ client: healthClient })
  if (response.error) {
    const status = response.response?.status
    const kind = status === 401 ? 'unauthorized' : status === 403 ? 'forbidden' : 'request'
    throw new DependencyHealthReadError(kind)
  }
  const dependencies = response.data?.data
  if (!isRecord(dependencies)) {
    throw new DependencyHealthReadError('invalid-response')
  }
  for (const [key, value] of Object.entries(dependencies)) {
    if (!key.trim() || !isRecord(value) || typeof value.status !== 'string' || typeof value.integration !== 'string') {
      throw new DependencyHealthReadError('invalid-response')
    }
  }
  return dependencies as Record<string, DependencyStatusDto>
}

export type DependencyHealthReadErrorKind = 'unauthorized' | 'forbidden' | 'invalid-response' | 'request'

export class DependencyHealthReadError extends Error {
  constructor(readonly kind: DependencyHealthReadErrorKind) {
    super(kind === 'invalid-response' ? '依赖状态响应格式无法识别。' : '依赖状态暂时无法读取。')
    this.name = 'DependencyHealthReadError'
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}
