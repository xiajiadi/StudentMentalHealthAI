import { createClient, createConfig } from '@/api/generated/client'
import { healthDependencies } from '@/api/generated/sdk.gen'
import type { DependencyStatusDto } from '@/api/generated/types.gen'

const healthClient = createClient(createConfig({
  baseUrl: import.meta.env.VITE_API_BASE_URL || '/',
  credentials: 'include',
}))

export async function readDependencyHealth(): Promise<Record<string, DependencyStatusDto>> {
  const response = await healthDependencies({ client: healthClient })
  if (response.error) throw new Error('依赖状态暂时无法读取。')
  const dependencies = response.data?.data
  if (!dependencies || typeof dependencies !== 'object' || Array.isArray(dependencies)) {
    throw new Error('依赖状态响应格式无法识别。')
  }
  return dependencies
}
