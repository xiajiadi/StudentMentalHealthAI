<script setup lang="ts">
import AuthLayout from '@/layouts/AuthLayout.vue'
import FocusLayout from '@/layouts/FocusLayout.vue'
import WorkspaceLayout from '@/layouts/WorkspaceLayout.vue'
import { computed, onBeforeUnmount, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const routeProgressVisible = ref(false)
const routeProgressComplete = ref(false)
let routeProgressStartTimer: ReturnType<typeof setTimeout> | undefined
let routeProgressHideTimer: ReturnType<typeof setTimeout> | undefined

const finishRouteProgress = () => {
  if (routeProgressStartTimer !== undefined) {
    clearTimeout(routeProgressStartTimer)
    routeProgressStartTimer = undefined
  }
  if (!routeProgressVisible.value) return

  routeProgressComplete.value = true
  if (routeProgressHideTimer !== undefined) clearTimeout(routeProgressHideTimer)
  routeProgressHideTimer = setTimeout(() => {
    routeProgressVisible.value = false
    routeProgressComplete.value = false
    routeProgressHideTimer = undefined
  }, 220)
}

const removeRouteStartHook = router.beforeEach(() => {
  if (routeProgressHideTimer !== undefined) {
    clearTimeout(routeProgressHideTimer)
    routeProgressHideTimer = undefined
  }
  routeProgressComplete.value = false
  if (routeProgressVisible.value || routeProgressStartTimer !== undefined) return
  routeProgressStartTimer = setTimeout(() => {
    routeProgressVisible.value = true
    routeProgressStartTimer = undefined
  }, 100)
})
const removeRouteFinishHook = router.afterEach(finishRouteProgress)
const removeRouteErrorHook = router.onError(finishRouteProgress)

onBeforeUnmount(() => {
  removeRouteStartHook()
  removeRouteFinishHook()
  removeRouteErrorHook()
  if (routeProgressStartTimer !== undefined) clearTimeout(routeProgressStartTimer)
  if (routeProgressHideTimer !== undefined) clearTimeout(routeProgressHideTimer)
})

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
  <div
    v-if="routeProgressVisible"
    class="route-progress"
    :class="{ 'route-progress--complete': routeProgressComplete }"
    aria-hidden="true"
  ></div>
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

.route-progress {
  position: fixed;
  z-index: 2000;
  top: 0;
  left: 0;
  width: 100%;
  height: 2px;
  overflow: hidden;
  background: linear-gradient(90deg, #00addf, #56d5ee);
  box-shadow: 0 0 8px rgb(0 173 223 / 35%);
  transform: scaleX(.84);
  transform-origin: left center;
  transition: transform 180ms cubic-bezier(.2, .75, .25, 1);
}

.route-progress::after {
  position: absolute;
  inset: 0 auto 0 0;
  width: 26%;
  content: "";
  background: linear-gradient(90deg, transparent, rgb(255 255 255 / 72%), transparent);
  animation: route-progress-glide 980ms ease-in-out infinite;
}

.route-progress--complete {
  transform: scaleX(1);
}

@keyframes route-progress-glide {
  from { transform: translateX(-110%); }
  to { transform: translateX(430%); }
}
</style>
