<template>
  <router-view />
</template>

<script setup lang="ts">
import { watch } from "vue";
import { useConfigStore } from "@/stores/config";
import { useUserStore } from "@/stores/user";

const userStore = useUserStore();
const configStore = useConfigStore();
watch(() => userStore.isLoggedIn, (loggedIn) => {
  if (loggedIn) configStore.ensureLoaded();
}, { immediate: true });
</script>
