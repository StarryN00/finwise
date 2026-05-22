<template>
  <AppLayout>
    <router-view />
  </AppLayout>
</template>

<script setup>
import { onMounted } from 'vue'
import AppLayout from './components/AppLayout.vue'
import { useWorkspaceStore } from './stores/workspace'

const workspace = useWorkspaceStore()

onMounted(() => {
  workspace.loadWorkspace()
})
</script>
