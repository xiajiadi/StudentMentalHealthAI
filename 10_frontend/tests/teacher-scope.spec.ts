import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import TeacherOverviewView from '@/views/teacher/TeacherOverviewView.vue'
import TeacherStudentsView from '@/views/teacher/TeacherStudentsView.vue'
import TeacherStudentDetailView from '@/views/teacher/TeacherStudentDetailView.vue'

const api = vi.hoisted(() => ({
  getTeacherOverview: vi.fn(),
  getTeacherStudent: vi.fn(),
}))

vi.mock('@/services/mock-api', () => ({ frontendApi: api }))

describe('Teacher Scope A views', () => {
  it('explains the missing privacy-safe task summary without reading individual records', () => {
    const wrapper = mount(TeacherOverviewView)

    expect(wrapper.text()).toContain('班级任务进度')
    expect(wrapper.text()).toContain('安全的任务进度暂不可读取')
    expect(wrapper.text()).toContain('小组汇总抑制规则')
    expect(wrapper.text()).toContain('当前不可用状态不代表班级没有任务')
    expect(api.getTeacherOverview).not.toHaveBeenCalled()
    expect(api.getTeacherStudent).not.toHaveBeenCalled()
  })

  it.each([
    ['task progress list', TeacherStudentsView],
    ['individual detail route', TeacherStudentDetailView],
  ])('does not disclose individual assessment history on the %s page', (_name, view) => {
    const wrapper = mount(view)

    expect(wrapper.text()).toContain('任务级')
    expect(wrapper.text()).not.toContain('ASSESS_')
    expect(wrapper.text()).not.toContain('SUBJ_')
    expect(api.getTeacherOverview).not.toHaveBeenCalled()
    expect(api.getTeacherStudent).not.toHaveBeenCalled()
  })
})
