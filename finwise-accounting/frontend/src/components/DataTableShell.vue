<script setup>
defineProps({
  title: {
    type: String,
    required: true,
  },
  description: {
    type: String,
    default: '',
  },
  actionLabel: {
    type: String,
    default: '',
  },
})

defineEmits(['action'])
</script>

<template>
  <section class="table-shell">
    <header class="table-shell__header">
      <div>
        <h2 class="section-title">{{ title }}</h2>
        <p v-if="description" class="caption">{{ description }}</p>
      </div>
      <div class="table-shell__tools">
        <slot name="filters" />
        <el-button v-if="actionLabel" type="primary" @click="$emit('action')">
          {{ actionLabel }}
        </el-button>
      </div>
    </header>
    <div class="table-shell__body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.table-shell {
  width: 100%;
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius);
  background: var(--fw-surface);
}

.table-shell__header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 16px;
  border-bottom: 1px solid var(--fw-line);
}

.table-shell__header .caption {
  margin: 4px 0 0;
}

.table-shell__tools {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  min-width: 280px;
}

.table-shell__body {
  min-width: 0;
  padding: 0;
}

@media (max-width: 900px) {
  .table-shell__header {
    display: grid;
  }

  .table-shell__tools {
    justify-content: start;
    min-width: 0;
  }
}
</style>
