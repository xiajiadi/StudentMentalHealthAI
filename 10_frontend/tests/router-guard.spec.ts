import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import router from '@/router'
import { useSessionStore } from '@/stores/session'

describe('角色路由守卫', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    useSessionStore().signOut()
    await router.push('/login')
  })

  it('未登录访问受保护页面会回到登录并保留目标地址', async () => {
    await router.push('/teacher/overview')
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBe('/teacher/overview')
  })

  it('角色不能跨越自己的工作区', async () => {
    useSessionStore().signIn({ userId: 'USER_demo_teacher', role: 'teacher', subjectId: null, displayName: '演示教师', initials: '师' })
    await router.push('/reviewer/queue')
    expect(router.currentRoute.value.name).toBe('teacher-overview')
  })

  it('允许复核员进入安全复核队列', async () => {
    useSessionStore().signIn({ userId: 'USER_demo_reviewer', role: 'reviewer', subjectId: null, displayName: '演示复核员', initials: '复' })
    await router.push('/reviewer/queue')
    expect(router.currentRoute.value.name).toBe('reviewer-queue')
  })

  it('心理专业人员只能进入专业工作区，安全复核员角色保持独立', async () => {
    useSessionStore().signIn({ userId: 'USER_demo_specialist', role: 'psychological_specialist', subjectId: null, displayName: '演示心理专业人员', initials: '专' })
    await router.push('/specialist/tasks')
    expect(router.currentRoute.value.name).toBe('specialist-workspace')
    expect(router.currentRoute.value.meta.roles).toEqual(['psychological_specialist'])
    await router.push('/reviewer/queue')
    expect(router.currentRoute.value.name).toBe('specialist-workspace')
  })

  it('学校管理员进入管理工作区且不能进入安全复核队列', async () => {
    useSessionStore().signIn({ userId: 'USER_demo_admin', role: 'school_admin', subjectId: null, displayName: '演示学校管理员', initials: '管' })
    await router.push('/admin/users')
    expect(router.currentRoute.value.name).toBe('admin-workspace')
    expect(router.currentRoute.value.meta.roles).toEqual(['school_admin'])
    await router.push('/reviewer/queue')
    expect(router.currentRoute.value.name).toBe('admin-workspace')
  })
})
