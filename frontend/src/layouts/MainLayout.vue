<template>
  <t-layout class="app-layout">
    <!-- 侧边栏 -->
    <t-aside :width="collapsed ? '64px' : '232px'" class="app-aside">
      <div class="logo" :class="{ collapsed }">
        <t-icon name="task" class="logo-mark" />
        <span v-if="!collapsed" class="logo-text">工单管理</span>
      </div>
      <t-menu
        :value="activeMenu"
        :collapsed="collapsed"
        theme="dark"
        @change="onMenuChange"
      >
        <t-submenu v-for="group in menuGroups" :key="group.label" :value="group.label" :title="group.label">
          <template #icon><t-icon :name="group.icon" class="menu-icon" /></template>
          <t-menu-item v-for="item in group.items" :key="item.path" :value="item.path">
            <template #icon><t-icon :name="item.icon" class="menu-icon" /></template>
            {{ item.title }}
          </t-menu-item>
        </t-submenu>
      </t-menu>
      <div v-if="!collapsed" class="aside-footer">
        <div class="sync-status">
          工单管理平台
        </div>
      </div>
    </t-aside>

    <t-layout>
      <!-- 顶栏 -->
      <t-header class="app-header">
        <div class="header-left">
          <t-button theme="default" variant="text" shape="square" @click="collapsed = !collapsed">
            <template #icon><t-icon :name="collapsed ? 'menu-unfold' : 'menu-fold'" /></template>
          </t-button>
          <t-breadcrumb :max-item="4">
            <t-breadcrumb-item v-for="(item, i) in breadcrumbs" :key="i" :to="i < breadcrumbs.length - 1 ? item.path : undefined">
              {{ item.title }}
            </t-breadcrumb-item>
          </t-breadcrumb>
        </div>
        <div class="header-right">
          <t-tooltip content="重新载入当前页面">
            <t-button theme="default" variant="text" shape="square" @click="reload">
              <template #icon><t-icon name="refresh" /></template>
            </t-button>
          </t-tooltip>
          <t-popup v-model="popupVisible" trigger="click" placement="bottom-right" :overlay-inner-style="{ padding: 0 }" :show-arrow="false">
            <t-badge :count="overdueCount" :offset="[-2, 6]">
              <t-button theme="default" variant="text" shape="square">
                <template #icon><t-icon name="notification" /></template>
              </t-button>
            </t-badge>
            <template #content>
              <div class="notif-panel">
                <div class="notif-head">消息通知</div>
                <div v-if="!overdueItems.length && !todoItems.length" class="notif-empty">暂无逾期或待办工单</div>
                <template v-else>
                  <div v-if="overdueItems.length" class="notif-group">
                    <div class="notif-group-title overdue">逾期工单（{{ overdueItems.length }}）</div>
                    <div v-for="it in overdueItems" :key="it.id" class="notif-item" @click="openWorkOrder(it.id)">
                      <span class="notif-code">{{ it.code }}</span>
                      <span class="notif-title">{{ it.title }}</span>
                      <span class="notif-meta">逾期 {{ it.overdue_days }} 天 · {{ it.person || "未派发" }}</span>
                    </div>
                  </div>
                  <div v-if="todoItems.length" class="notif-group">
                    <div class="notif-group-title">待办工单（{{ todoItems.length }}）</div>
                    <div v-for="it in todoItems" :key="it.id" class="notif-item" @click="openWorkOrder(it.id)">
                      <span class="notif-code">{{ it.code }}</span>
                      <span class="notif-title">{{ it.title }}</span>
                      <span class="notif-meta">{{ statusLabel(it.status) }} · {{ it.person || "未派发" }}</span>
                    </div>
                  </div>
                </template>
              </div>
            </template>
          </t-popup>
          <t-divider v-if="store.isAdmin" layout="vertical" />
          <t-button
            v-if="store.isAdmin"
            :theme="paused ? 'danger' : 'warning'"
            :variant="paused ? 'base' : 'outline'"
            size="small"
            :loading="pauseLoading"
            @click="onTogglePause"
          >
            {{ paused ? "恢复发单" : "暂停发单" }}
          </t-button>
          <t-divider layout="vertical" />
          <span class="user-name">{{ store.user?.name || "管理员" }}</span>
          <t-button theme="default" variant="text" size="small" @click="doLogout">退出</t-button>
        </div>
      </t-header>

      <!-- 内容区 -->
      <t-content class="app-content">
        <t-alert
          v-if="paused"
          theme="warning"
          message="系统维护中：已暂停发单，新建 / 派发工单暂不可用"
          style="margin-bottom: 16px"
        />
        <router-view v-if="!refreshing" v-slot="{ Component }">
          <keep-alive include="WorkOrderList,DataPool,ClosedRecords,ProjectManage,UserManagement">
            <component :is="Component" />
          </keep-alive>
        </router-view>
      </t-content>
    </t-layout>
  </t-layout>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { getDashboardStats } from "@/api/dashboard";
import { getSystemPause, setSystemPause } from "@/api/config";
import { toast, confirmDialog } from "@/utils/feedback";
import { statusLabel } from "@/utils/wo-display";
import { useUserStore } from "@/stores/user";
import { MENU_GROUPS, FLAT_MENUS } from "@/menu";

const route = useRoute();
const router = useRouter();
const store = useUserStore();
const collapsed = ref(false);
const refreshing = ref(false);
const overdueCount = ref(0);
const overdueItems = ref<any[]>([]);
const todoItems = ref<any[]>([]);
const popupVisible = ref(false);
const paused = ref(false);
const pauseLoading = ref(false);

async function loadPauseState() {
  try {
    const r = await getSystemPause();
    paused.value = !!r.paused;
  } catch {
    /* ignore */
  }
}

async function onTogglePause() {
  if (pauseLoading.value) return;
  const next = !paused.value;
  const ok = await confirmDialog(
    next
      ? "确定「暂停发单」？开启后所有新建/派发工单入口将被拦截（含手动建单、外部API、数据池生成、计划/异常自动导入、按月派发、措施工单、Excel/Agent导入）。"
      : "确定「恢复发单」？",
    next ? "暂停发单" : "恢复发单"
  );
  if (!ok) return;
  pauseLoading.value = true;
  try {
    const r = await setSystemPause(next);
    paused.value = !!r.paused;
    toast.success(next ? "已暂停发单" : "已恢复发单");
  } catch (e: any) {
    toast.error(e?.message || "操作失败");
  } finally {
    pauseLoading.value = false;
  }
}

const menus = computed(() => FLAT_MENUS);

// 按角色过滤菜单（admin 恒全量，其余角色按已保存的菜单权限配置过滤）
const menuGroups = computed(() =>
  MENU_GROUPS.map((g) => ({
    ...g,
    items: g.items.filter((item) => store.canAccessMenu(g.label, item.title)),
  })).filter((g) => g.items.length > 0)
);

const activeMenu = computed(() => {
  // 精确匹配或前缀
  const path = route.path;
  const exact = menus.value.find((m) => m.path === path);
  if (exact) return exact.path;
  const prefix = menus.value.find((m) => m.path !== "/" && path.startsWith(m.path));
  return prefix?.path ?? "/";
});

// 动态面包屑
const breadcrumbs = computed(() => {
  const crumbs: { title: string; path: string }[] = [];
  const path = route.path;
  // 首页不加面包屑
  if (path === "/" || path === "") return crumbs;

  // 从 matched 中获取层级：matched[0] 是 MainLayout，后续是子路由
  const matched = route.matched;
  // 找父级页面：路径前缀匹配的菜单项
  const parentPath = "/" + path.split("/").slice(1, -1).join("/");
  if (parentPath !== "/" && parentPath !== path) {
    const parentMenu = menus.value.find((m) => m.path === parentPath);
    if (parentMenu) {
      crumbs.push({ title: parentMenu.title, path: parentPath });
    }
  }
  // 当前页
  if (route.meta.title) {
    crumbs.push({ title: route.meta.title as string, path: path });
  }
  return crumbs;
});

function onMenuChange(path: string) {
  router.push(path);
}

function doLogout() {
  store.logout();
  router.push("/login");
}

function openWorkOrder(id: number) {
  popupVisible.value = false;
  router.push(`/work-orders/${id}`);
}

async function reload() {
  refreshing.value = true;
  setTimeout(() => (refreshing.value = false), 50);
}

onMounted(async () => {
  loadPauseState();
  try {
    const s = await getDashboardStats();
    overdueCount.value = s.overdue;
    overdueItems.value = s.overdue_items || [];
    todoItems.value = s.todo_items || [];
  } catch {
    /* ignore */
  }
});
</script>

<style scoped>
.app-layout { height: 100vh; width: 100%; min-width: 0; overflow: hidden; }
.app-layout :deep(.t-layout) { min-width: 0; }
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
.user-name { font-size: 13px; color: var(--text); }

.notif-panel { width: 320px; max-height: 380px; overflow-y: auto; background: var(--card); border-radius: 6px; }
.notif-head { padding: 10px 14px; font-size: 13px; font-weight: 600; border-bottom: 1px solid var(--border); }
.notif-empty { padding: 20px 14px; color: var(--muted); font-size: 12px; text-align: center; }
.notif-group { padding: 6px 0; }
.notif-group + .notif-group { border-top: 1px dashed var(--border); }
.notif-group-title { padding: 6px 14px; font-size: 11px; color: var(--muted); font-weight: 600; }
.notif-group-title.overdue { color: var(--red); }
.notif-item { display: flex; align-items: center; gap: 8px; padding: 6px 14px; cursor: pointer; font-size: 12px; }
.notif-item:hover { background: var(--bg); }
.notif-code { color: #5b9bff; font-weight: 600; white-space: nowrap; }
.notif-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.notif-meta { color: var(--muted); font-size: 11px; white-space: nowrap; }

.app-content {
  padding: 20px;
  min-width: 0;
  max-width: 100%;
  overflow-y: auto;
  overflow-x: hidden;
  background: var(--bg);
}
</style>
