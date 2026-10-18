<template>
  <span class="app-loading-dots" aria-hidden="true">
    <i></i><i></i><i></i>
  </span>
</template>

<style scoped>
.app-loading-dots { display: inline-flex; align-items: center; gap: 3px; margin-left: 5px; vertical-align: middle; }
.app-loading-dots i { width: 3px; height: 3px; border-radius: 50%; background: currentcolor; opacity: .3; animation: app-loading-dot 900ms ease-in-out infinite; }
.app-loading-dots i:nth-child(2) { animation-delay: 130ms; }
.app-loading-dots i:nth-child(3) { animation-delay: 260ms; }
@keyframes app-loading-dot { 0%, 70%, 100% { opacity: .3; transform: translateY(0); } 35% { opacity: .9; transform: translateY(-2px); } }
</style>
