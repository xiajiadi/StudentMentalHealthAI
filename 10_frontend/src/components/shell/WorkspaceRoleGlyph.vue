<script setup lang="ts">
import type { Role } from '@/types/contracts'

defineProps<{ role: Role }>()
</script>

<template>
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.55" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
    <path v-if="role === 'student'" d="M4 15.5c3.3.1 6 1.4 8 3.8 2-2.4 4.7-3.7 8-3.8v3.3c-3.3 0-6 1-8 2.7-2-1.7-4.7-2.7-8-2.7ZM12 3v3.4m-3.6-2 1.2.9m6-1-1.2 1M12 9.2c-2 0-3.3 1.4-3.3 3.2 0 1.4 1 2.4 3.3 4 2.3-1.6 3.3-2.6 3.3-4 0-1.8-1.7-3.2-3.3-3.2Z" />
    <path v-else-if="role === 'teacher'" d="M6 4.5h14V14H9.5m-5-9.5v3m5 .5h6m-2 3h3M7.2 21v-3.5l4.3-2.5-1-1.6-4.3 1.8H5c-1.7 0-2.5 1-2.5 2.6V21m5.3-9.1a2 2 0 1 1-4 0 2 2 0 1 1 4 0Z" />
    <path v-else-if="role === 'psychological_specialist'" d="M4 9a4.2 4.2 0 0 1 8-1.8A4.2 4.2 0 0 1 20 9c0 3.9-4 7.3-8 10-4-2.7-8-6.1-8-10Zm2.7 3H10l1.1-2.2 1.5 4.2 1.1-2H17m2.2-8 .8 1.2 1.4.4-1 .9v1.4" />
    <path v-else-if="role === 'school_admin'" d="M4 8.5 12 4l8 4.5v2H4Zm1.5 2V18h13v-7.5M3.5 20.5h17m-11-2.5v-3.5h5V18m-2.5-14V2" />
    <path v-else d="M5.5 4.5h13v15h-13zm3.5 7.8 2 2 4.5-4.5" />
  </svg>
</template>
