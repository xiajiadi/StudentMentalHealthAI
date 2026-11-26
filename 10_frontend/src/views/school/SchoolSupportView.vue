<script setup lang="ts">
import { computed } from 'vue'
import { useSessionStore } from '@/stores/session'
import type { TeacherReferral } from '@/services/school-support'
import SchoolSupportWorkspace from './SchoolSupportWorkspace.vue'

const props = defineProps<{ audience: 'student' | 'teacher' | 'specialist'; initialReferral?: TeacherReferral }>()
const session = useSessionStore()
const role = computed(() => props.audience === 'specialist' ? 'psychological_specialist' : props.audience)
const scope = computed(() => JSON.stringify([session.user?.userId, session.user?.activeContext]))
</script>

<template>
  <SchoolSupportWorkspace v-if="session.user?.activeContext?.role === role" :key="scope" :audience="audience" :initial-referral="initialReferral" />
  <section v-else class="content-wrap" role="status">请先选择有权限的学校身份。</section>
</template>
