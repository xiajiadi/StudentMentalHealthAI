import { describe, expect, it } from 'vitest'
import { adminWorkspaceActions } from '@/components/admin/admin-workspace-actions'

describe('admin account actions', () => {
  it('routes pending accounts to the one-time credentials workflow', () => {
    const action = adminWorkspaceActions.find((item) => item.id === 'admin-activate-accounts')
    expect(action).toMatchObject({
      label: '批量发行一次性凭据',
      to: '/admin/users?directoryAction=issue-credentials',
    })
    expect(action?.description).not.toContain('密码')
    expect(action?.keywords).toContain('一次性凭据')
  })
})
