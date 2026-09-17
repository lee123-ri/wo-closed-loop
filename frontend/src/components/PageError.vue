<template>
  <section class="page-error" role="alert">
    <t-icon name="error-circle" class="page-error-icon" />
    <h2>{{ title }}</h2>
    <p>{{ message }}</p>
    <t-button variant="outline" @click="$emit('action')">{{ actionLabel }}</t-button>
  </section>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ title: string; message: string; actionLabel?: string }>(), {
  actionLabel: "重试",
});
defineEmits<{ (e: "action"): void }>();
</script>

<style scoped>
.page-error {
  max-width: 480px;
  margin: 40px auto;
  padding: 32px 24px;
  text-align: center;
  color: var(--text);
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
}
.page-error-icon { font-size: 32px; color: var(--red); margin-bottom: 12px; }
h2 { font-size: var(--fs-h1); margin-bottom: 6px; }
p { color: var(--muted); margin-bottom: 18px; }
</style>
