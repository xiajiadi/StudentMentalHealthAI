import { createRouter, createWebHistory } from 'vue-router'
import type { Role } from '@/types/contracts'
import { useSessionStore } from '@/stores/session'
import { frontendApi } from '@/services/mock-api'

declare module 'vue-router' {
  interface RouteMeta {
    public?: boolean
    roles?: Role[]
    layout?: 'auth' | 'student' | 'teacher' | 'reviewer' | 'workspace' | 'focus'
  }
}

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior: (to, _from, savedPosition) => savedPosition ?? (to.hash ? { el: to.hash, behavior: 'smooth' } : { top: 0 }),
  routes: [
    { path: '/', redirect: '/login' },
    { path: '/login', name: 'login', component: () => import('@/views/auth/LoginView.vue'), meta: { public: true, layout: 'auth' } },
    { path: '/student', redirect: '/student/home' },
    { path: '/student/home', name: 'student-home', component: () => import('@/views/student/StudentHomeView.vue'), meta: { roles: ['student'], layout: 'workspace' } },
    { path: '/student/assessments', name: 'student-assessments', component: () => import('@/views/student/StudentAssessmentsView.vue'), meta: { roles: ['student'], layout: 'workspace' } },
    { path: '/student/feedback', name: 'student-feedback', component: () => import('@/views/student/StudentFeedbackView.vue'), meta: { roles: ['student'], layout: 'workspace' } },
    { path: '/student/assessment', name: 'student-assessment', component: () => import('@/views/student/AssessmentView.vue'), meta: { roles: ['student'], layout: 'focus' } },
    { path: '/student/assessment/:id', name: 'student-assessment-resume', component: () => import('@/views/student/AssessmentView.vue'), meta: { roles: ['student'], layout: 'focus' } },
    { path: '/student/assessment/:id/result', name: 'student-assessment-result', component: () => import('@/views/student/AssessmentResultView.vue'), meta: { roles: ['student'], layout: 'workspace' } },
    { path: '/student/research/tasks/:taskRef', name: 'student-research-task-start', component: () => import('@/views/student/ResearchAssessmentView.vue'), meta: { roles: ['student'], layout: 'focus' } },
    { path: '/student/research/sessions/:sessionRef', name: 'student-research-session-resume', component: () => import('@/views/student/ResearchAssessmentView.vue'), meta: { roles: ['student'], layout: 'focus' } },
    { path: '/student/support', name: 'student-support', component: () => import('@/views/student/SupportChatView.vue'), meta: { roles: ['student'], layout: 'workspace' } },
    { path: '/student/history', name: 'student-history', component: () => import('@/views/student/StudentHomeView.vue'), meta: { roles: ['student'], layout: 'workspace' } },
    { path: '/student/reports/:id', name: 'student-report-detail', component: () => import('@/views/student/StudentResultView.vue'), meta: { roles: ['student'], layout: 'workspace' } },
    { path: '/student/result/:id', name: 'student-result', component: () => import('@/views/student/StudentResultView.vue'), meta: { roles: ['student'], layout: 'workspace' } },
    { path: '/teacher', redirect: '/teacher/overview' },
    { path: '/teacher/overview', name: 'teacher-overview', component: () => import('@/views/teacher/TeacherOverviewView.vue'), meta: { roles: ['teacher'], layout: 'workspace' } },
    { path: '/teacher/students', name: 'teacher-students', component: () => import('@/views/teacher/TeacherStudentsView.vue'), meta: { roles: ['teacher'], layout: 'workspace' } },
    { path: '/teacher/students/:id', name: 'teacher-student-detail', component: () => import('@/views/teacher/TeacherStudentDetailView.vue'), meta: { roles: ['teacher'], layout: 'workspace' } },
    { path: '/specialist', redirect: '/specialist/overview' },
    { path: '/specialist/:section(overview|resources|tasks|cat)', name: 'specialist-workspace', component: () => import('@/views/specialist/SpecialistWorkspaceView.vue'), meta: { roles: ['psychological_specialist'], layout: 'workspace' } },
    { path: '/admin', redirect: '/admin/overview' },
    { path: '/admin/:section(overview|users|settings)', name: 'admin-workspace', component: () => import('@/views/admin/AdminWorkspaceView.vue'), meta: { roles: ['school_admin'], layout: 'workspace' } },
    { path: '/reviewer', redirect: '/reviewer/queue' },
    { path: '/reviewer/queue', name: 'reviewer-queue', component: () => import('@/views/reviewer/ReviewQueueView.vue'), meta: { roles: ['reviewer'], layout: 'workspace' } },
    { path: '/reviewer/cases/:id', name: 'reviewer-detail', component: () => import('@/views/reviewer/ReviewDetailView.vue'), meta: { roles: ['reviewer'], layout: 'workspace' } },
    { path: '/404', name: 'not-found', component: () => import('@/views/NotFoundView.vue'), meta: { public: true } },
    { path: '/:pathMatch(.*)*', redirect: '/404' },
  ],
})

router.beforeEach(async (to) => {
  const session = useSessionStore()
  if (to.meta.public && to.name !== 'login') return true
  if (!session.isAuthenticated) {
    try {
      const restored = (await frontendApi.getCurrentUser()).data
      if (restored) session.signIn(restored)
    } catch {
      // The guard below gives the user a sign-in path when the local session cannot be restored.
    }
  }
  const needsContext = Boolean(session.user?.availableContexts?.length && !session.user.activeContext)
  if (needsContext) {
    return to.name === 'login' ? true : { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.meta.public) {
    if (to.name === 'login' && session.role) return roleHome(session.role)
    return true
  }
  if (!session.isAuthenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  const allowedRoles = to.meta.roles
  const authorizedRoles = session.user?.availableContexts?.length ? [] : session.user?.authorizedRoles ?? []
  if (allowedRoles && !allowedRoles.some((role) => role === session.role || authorizedRoles.includes(role))) {
    return session.role ? roleHome(session.role) : { name: 'login' }
  }
  return true
})

function roleHome(role: Role) {
  const routes: Record<Role, string> = {
    student: '/student/home', teacher: '/teacher/overview', psychological_specialist: '/specialist/overview', school_admin: '/admin/overview', reviewer: '/reviewer/queue',
  }
  return routes[role]
}

export default router
