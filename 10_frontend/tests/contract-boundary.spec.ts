import { describe, expect, it } from 'vitest'
import {
  reviewCaseFixture,
  studentReportFixture,
  syntheticCitations,
  syntheticGeneration,
} from '@/mocks/fixtures'

describe('前端展示边界', () => {
  it('只使用可追踪的合成标识和引用', () => {
    expect(reviewCaseFixture.review_case_id).toMatch(/^REVIEW_demo_/)
    expect(reviewCaseFixture.subject_id).toMatch(/^SUBJ_demo_/)
    expect(syntheticGeneration.generation_id).toMatch(/^GEN_demo_/)
    expect(studentReportFixture.evidence.map((citation) => citation.chunk_id)).toEqual(
      syntheticCitations.map((citation) => citation.chunk_id),
    )
  })

  it('学生结果保留 Meaning → Data → Action → Evidence 顺序所需的数据', () => {
    expect(studentReportFixture.meaning.body).toBeTruthy()
    expect(studentReportFixture.data.dimensions).toHaveLength(4)
    expect(studentReportFixture.actions).toHaveLength(3)
    expect(studentReportFixture.evidence).toHaveLength(3)
    expect(JSON.stringify(studentReportFixture.data)).not.toMatch(/theta|se|vector|similarity/i)
  })

  it('需要人工确认时，生成状态不允许伪装为已生成', () => {
    expect(reviewCaseFixture.generationStatus).toBe('needs_review')
    expect(reviewCaseFixture.status).toBe('PENDING')
    expect(reviewCaseFixture.summary).toContain('普通个性化生成已暂停')
  })
})
