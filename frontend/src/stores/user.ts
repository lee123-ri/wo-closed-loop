import { defineStore } from "pinia";
import { ref, computed } from "vue";

export interface UserInfo {
  id: number;
  name: string;
  role: string;
  phone?: string;
  dingtalk_id?: string;
}

export interface Permissions {
  roles: string[];
  menu_groups: Record<string, Record<string, { roles: string[] }>>;
  actions: Record<string, { roles: string[] }>;
}

export const useUserStore = defineStore("user", () => {
  const user = ref<UserInfo | null>(null);
  const token = ref<string | null>(localStorage.getItem("wo_token"));
  const permissions = ref<Permissions | null>(null);

  const isLoggedIn = computed(() => !!token.value && !!user.value);
  const isAdmin = computed(() => user.value?.role === "admin");
  const isApprover = computed(() => user.value?.role === "admin" || user.value?.role === "approver");
  const role = computed(() => user.value?.role || "executor");

  function setAuth(t: string, u: UserInfo) {
    token.value = t;
    user.value = u;
    localStorage.setItem("wo_token", t);
  }

  function logout() {
    token.value = null;
    user.value = null;
    permissions.value = null;
    localStorage.removeItem("wo_token");
  }

  function canAccessMenu(group: string, item: string): boolean {
    if (!permissions.value) return true; // 权限未加载时允许
    const g = permissions.value.menu_groups[group];
    if (!g) return false;
    const it = g[item];
    if (!it) return false;
    return it.roles.includes(user.value?.role || "");
  }

  function canDo(action: string): boolean {
    if (!permissions.value) return true;
    const act = permissions.value.actions[action];
    if (!act) return false;
    return act.roles.includes(user.value?.role || "");
  }

  return { user, token, permissions, isLoggedIn, isAdmin, isApprover, role, setAuth, logout, canAccessMenu, canDo };
});