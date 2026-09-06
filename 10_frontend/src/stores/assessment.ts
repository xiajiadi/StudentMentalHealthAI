import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { CatQuestion } from '@/types/view-models'

export const useAssessmentStore = defineStore('assessment', () => {
  const assessmentId = ref<string | null>(null)
  const subjectId = ref<string | null>(null)
  const question = ref<CatQuestion | null>(null)
  const currentIndex = ref(0)
  const answeredCount = ref(0)
  const canComplete = ref(false)
  const maxItems = ref<number | null>(null)
  const isActive = computed(() => assessmentId.value !== null && question.value !== null)

  const start = (input: {
    assessmentId: string
    subjectId: string
    question: CatQuestion | null
    currentIndex: number
    answeredCount: number
    canComplete: boolean
    maxItems: number
  }) => {
    assessmentId.value = input.assessmentId
    subjectId.value = input.subjectId
    question.value = input.question
    currentIndex.value = input.currentIndex
    answeredCount.value = input.answeredCount
    canComplete.value = input.canComplete
    maxItems.value = input.maxItems
  }

  const update = (input: {
    question: CatQuestion | null
    currentIndex: number
    answeredCount: number
    canComplete: boolean
  }) => {
    question.value = input.question
    currentIndex.value = input.currentIndex
    answeredCount.value = input.answeredCount
    canComplete.value = input.canComplete
  }

  const reset = () => {
    assessmentId.value = null
    subjectId.value = null
    question.value = null
    currentIndex.value = 0
    answeredCount.value = 0
    canComplete.value = false
    maxItems.value = null
  }

  return {
    assessmentId,
    subjectId,
    question,
    currentIndex,
    answeredCount,
    canComplete,
    maxItems,
    isActive,
    start,
    update,
    reset,
  }
})
