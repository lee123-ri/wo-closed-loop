<template>
  <t-layout class="app-layout">
    <!-- 侧边栏 -->
    <t-aside :width="collapsed ? '64px' : '232px'" class="app-aside">
      <div class="logo" :class="{ collapsed }">
        <span class="logo-mark">◆</span>
        <span v-if="!collapsed" class="logo-text">软工单闭环管理</span>
      </div>
      <t-menu
        :value="activeMenu"
        :collapsed="collapsed"
        theme="dark"
        @change="onMenuChange"
      >
        <t-submenu v-for="group in menuGroups" :key="group.label" :value="group.label" :title="group.label">
          <template #icon><span class="menu-icon">{{ group.icon }}</span></template>
          <t-menu-item v-for="item in group.items" :key="item.path" :value="item.path">
            <template #icon><span class="menu-icon">{{ item.icon }}</span></template>
            {{ item.title }}
          </t-menu-item>
        </t-submenu>
      </t-menu>
      <div v-if="!collapsed" class="aside-footer">
        <div class="sync-status">
          <span class="dot online"></span> 软工单闭环管理平台
        </div>
      </div>
    </t-aside>

    <t-layout>
      <!-- 顶栏 -->
      <t-header class="app-header">
        <div class="header-left">
          <t-button theme="default" variant="text" shape="square" @click="collapsed = !collapsed">
            <template #icon><span class="fold-icon">{{ collapsed ? '☰' : '◁' }}</span></template>
          </t-button>
          <t-breadcrumb :max-item="4">
            <t-breadcrumb-item>软工单闭环管理</t-breadcrumb-item>
            <t-breadcrumb-item>{{ currentTitle }}</t-breadcrumb-item>
          </t-breadcrumb>
        </div>
        <div class="header-right">
          <t-tooltip content="刷新工作台数据">
            <t-button theme="default" variant="text" shape="square" @click="reload">
              <template #icon><span>↻</span></template>
            </t-button>
          </t-tooltip>
          <t-badge :count="overdueCount" :offset="[-2, 6]">
            <t-button theme="default" variant="text" shape="square">
              <template #icon><span>🔔</span></template>
            </t-button>
          </t-badge>
          <t-divider layout="vertical" />
          <span class="env-tag" :class="env">{{ env }}</span>
          <span class="user-name">{{ store.user?.name || "管理员" }}</span>
          <t-avatar size="32px">{{ (store.user?.name || "管")[0] }}</t-avatar>
          <t-button theme="default" variant="text" size="small" @click="doLogout">退出</t-button>
        </div>
      </t-header>

      <!-- 内容区 -->
      <t-content class="app-content">
        <router-view v-if="!refreshing" v-slot="{ Component }">
          <component :is="Component" />
        </router-view>
      </t-content>
    </t-layout>
  </t-layout>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { getDashboardStats } from "@/api/dashboard";
import { useUserStore } from "@/stores/user";

const route = useRoute();
const router = useRouter();
const store = useUserStore();
const collapsed = ref(false);
const refreshing = ref(false);
const overdueCount = ref(0);

const menus = computed(() => [
  { path: "/", icon: "▣", title: "管理看板" },
  { path: "/my", icon: "👤", title: "我的工单" },
  { path: "/work-orders", icon: "☰", title: "工单列表" },
  { path: "/create", icon: "＋", title: "新建工单" },
  { path: "/pool", icon: "◫", title: "数据池" },
  { path: "/closed", icon: "☑", title: "闭环记录" },
  { path: "/projects", icon: "◈", title: "项目管理" },
  { path: "/sop", icon: "📖", title: "SOP知识库" },
  { path: "/users", icon: "👥", title: "用户管理" },
  { path: "/config", icon: "⚙", title: "规则配置" },
  { path: "/audit-log", icon: "📋", title: "操作日志" },
]);

const allMenuGroups = [
  {
    label: "工作台",
    icon: "▣",
    items: [
      { path: "/", icon: "▣", title: "管理看板" },
      { path: "/my", icon: "👤", title: "我的工单" },
    ],
  },
  {
    label: "工单管理",
    icon: "☰",
    items: [
      { path: "/work-orders", icon: "☰", title: "工单列表" },
      { path: "/create", icon: "＋", title: "新建工单" },
      { path: "/closed", icon: "☑", title: "闭环记录" },
    ],
  },
  {
    label: "基础数据",
    icon: "◈",
    items: [
      { path: "/projects", icon: "◈", title: "项目管理" },
      { path: "/pool", icon: "◫", title: "数据池" },
      { path: "/sop", icon: "📖", title: "SOP知识库" },
    ],
  },
  {
    label: "系统设置",
    icon: "⚙",
    items: [
      { path: "/users", icon: "👥", title: "用户管理" },
      { path: "/config", icon: "⚙", title: "规则配置" },
      { path: "/audit-log", icon: "📋", title: "操作日志" },
    ],
  },
];

// 按角色过滤菜单
const menuGroups = computed(() => {
  if (store.isAdmin || store.isApprover) return allMenuGroups;
  return allMenuGroups
    .map((g) => ({
      ...g,
      items: g.items.filter((item) => {
        return store.canAccessMenu(g.label, item.title);
      }),
    }))
    .filter((g) => g.items.length > 0);
});

const activeMenu = computed(() => {
  // 精确匹配或前缀
  const path = route.path;
  const exact = menus.value.find((m) => m.path === path);
  if (exact) return exact.path;
  const prefix = menus.value.find((m) => m.path !== "/" && path.startsWith(m.path));
  return prefix?.path ?? "/";
});

const currentTitle = computed(() => (route.meta.title as string) || "工作台");
const env = import.meta.env.MODE || "development";

function onMenuChange(path: string) {
  router.push(path);
}

function doLogout() {
  store.logout();
  router.push("/login");
}

async function reload() {
  refreshing.value = true;
  setTimeout(() => (refreshing.value = false), 50);
}

onMounted(async () => {
  try {
    const s = await getDashboardStats();
    overdueCount.value = s.overdue;
  } catch {
    /* ignore */
  }
});
</script>

<style scoped>
.app-layout { height: 100vh; }
.app-aside {
  background: var(--sidebar-bg);
  transition: width 0.2s;
  display: flex;
  flex-direction: column;
}
.logo {
  height: 56px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 20px;
  color: #fff;
  font-size: 16px;
  font-weight: 700;
  border-bottom: 1px solid rgba(255,255,255,0.08);
  white-space: nowrap;
}
.logo.collapsed { padding: 0; justify-content: center; }
.logo-mark { color: #5b9bff; }
.app-aside :deep(.t-menu) { background: transparent; flex: 1; border-right: none; }
.menu-icon { font-size: 16px; }
.aside-footer { padding: 12px 20px; border-top: 1px solid rgba(255,255,255,0.08); }
.sync-status { color: #8c8c8c; font-size: 11px; display: flex; align-items: center; gap: 6px; }
.dot { width: 6px; height: 6px; border-radius: 50%; }
.dot.online { background: var(--green); box-shadow: 0 0 4px var(--green); }

.app-header {
  height: 56px;
  background: var(--card);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
}
.header-left { display: flex; align-items: center; gap: 12px; }
.header-right { display: flex; align-items: center; gap: 10px; }
.fold-icon { font-size: 16px; }
.env-tag { font-size: 10px; padding: 1px 6px; border-radius: 3px; background: #f0f0f0; color: #8c8c8c; }
.env-tag.development { background: #fff3e0; color: var(--amber); }
.env-tag.production { background: #e8f7ef; color: var(--green); }
.user-name { font-size: 13px; color: var(--text); }

.app-content {
  padding: 20px;
  overflow-y: auto;
  background: var(--bg);
}
</style>
