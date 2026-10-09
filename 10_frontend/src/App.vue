<script setup lang="ts">
import AuthLayout from '@/layouts/AuthLayout.vue'
import FocusLayout from '@/layouts/FocusLayout.vue'
import WorkspaceLayout from '@/layouts/WorkspaceLayout.vue'
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

const layout = computed(() => {
  switch (route.meta.layout) {
    case 'auth': return AuthLayout
    case 'focus': return FocusLayout
    case 'teacher':
    case 'reviewer':
    case 'student':
    case 'workspace': return WorkspaceLayout
    default: return undefined
  }
})
</script>

<template>
  <component :is="layout">
    <RouterView v-slot="{ Component }">
      <Transition name="route" mode="out-in">
        <component :is="Component" />
      </Transition>
    </RouterView>
  </component>
  <RouterView v-if="!layout" />
</template>

<style>
.route-enter-active,
.route-leave-active {
  transition: opacity var(--motion-fast) ease, transform var(--motion-fast) ease;
}

.route-enter-from {
  opacity: 0;
  transform: translateY(5px);
}

.route-leave-to {
  opacity: 0;
  transform: translateY(-3px);
}
</style>
