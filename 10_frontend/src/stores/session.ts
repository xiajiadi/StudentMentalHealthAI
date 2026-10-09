import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { Role } from '@/types/contracts'
import type { SessionUser } from '@/types/view-models'

export const useSessionStore = defineStore('session', () => {
  const user = ref<SessionUser | null>(null)

  const isAuthenticated = computed(() => user.value !== null)
  const role = computed<Role | null>(() => user.value?.role ?? null)

  const signIn = (input: { userId: string; role: Role; authorizedRoles?: Role[]; subjectId: string | null; displayName: string; initials: string }) => {
    user.value = {
      ...input,
      disclosure: input.role,
    }
  }

  const signOut = () => {
    user.value = null
  }

  return { user, role, isAuthenticated, signIn, signOut }
})
