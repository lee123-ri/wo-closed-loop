import { defineStore } from "pinia";
import { ref } from "vue";

export const useAppStore = defineStore("app", () => {
  const sidebarCollapsed = ref(false);
  const user = ref<{ id: number; name: string; role: string } | null>(null);

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value;
  }

  function setUser(u: any) {
    user.value = u;
  }

  return { sidebarCollapsed, user, toggleSidebar, setUser };
});
