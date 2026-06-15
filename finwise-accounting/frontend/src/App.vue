<template>
  <router-view v-if="isPublicLayout" />
  <AppLayout v-else>
    <router-view />
  </AppLayout>
</template>

<script setup>
import { computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppLayout from './components/AppLayout.vue'
import { useWorkspaceStore } from './stores/workspace'

const route = useRoute()
const workspace = useWorkspaceStore()
const isPublicLayout = computed(() => Boolean(route.meta.publicLayout))

watch(
  isPublicLayout,
  (publicLayout) => {
    if (!publicLayout) {
      workspace.loadWorkspace()
    }
  },
  { immediate: true },
)
</script>
