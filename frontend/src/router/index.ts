import { createRouter, createWebHistory } from "vue-router";
import { useUserStore } from "@/stores/user";
import { getMe, getPermissions } from "@/api/auth";
import { MENU_GROUPS, findMenuByPath } from "@/menu";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/login",
      name: "login",
      meta: { title: "登录" },
      component: () => import("@/views/LoginPage.vue"),
    },
    {
      path: "/",
      component: () => import("@/layouts/MainLayout.vue"),
      meta: { requiresAuth: true },
      children: [
        { path: "", name: "dashboard", meta: { title: "管理看板", icon: "▣" }, component: () => import("@/views/Dashboard.vue") },
        { path: "my", name: "my", meta: { title: "我的工单", icon: "👤" }, component: () => import("@/views/MyDashboard.vue") },
        { path: "work-orders", name: "list", meta: { title: "工单列表", icon: "☰" }, component: () => import("@/views/WorkOrderList.vue") },
        { path: "work-orders/:id", name: "detail", meta: { title: "工单详情" }, component: () => import("@/views/WorkOrderDetail.vue") },
        { path: "create", name: "create", meta: { title: "新建工单", icon: "＋" }, component: () => import("@/views/WorkOrderCreate.vue") },
        { path: "closed", name: "closed", meta: { title: "闭环记录", icon: "☑" }, component: () => import("@/views/ClosedRecords.vue") },
        { path: "pool", name: "pool", meta: { title: "数据池", icon: "◫" }, component: () => import("@/views/DataPool.vue") },
        { path: "dingtalk", name: "dingtalk", meta: { title: "钉钉集成", icon: "✆" }, component: () => import("@/views/DingTalkPage.vue") },
        { path: "config", name: "config", meta: { title: "规则配置", icon: "⚙" }, component: () => import("@/views/ConfigPage.vue") },
        { path: "users", name: "users", meta: { title: "用户管理", icon: "👥" }, component: () => import("@/views/UserManagement.vue") },
        { path: "organization", name: "organization", meta: { title: "用户与组织", icon: "👥" }, component: () => import("@/views/OrganizationCenter.vue") },
        { path: "projects", name: "projects", meta: { title: "项目管理", icon: "◈" }, component: () => import("@/views/ProjectManage.vue") },
        { path: "sop", name: "sop", meta: { title: "SOP知识库", icon: "📖" }, component: () => import("@/views/SOPBrowser.vue") },
        { path: "audit-log", name: "audit-log", meta: { title: "操作日志", icon: "📋" }, component: () => import("@/views/AuditLog.vue") },
      ],
    },
  ],
});

// 路由守卫
router.beforeEach(async (to, _from, next) => {
  const store = useUserStore();

  // 钉钉授权码落在根路径（回跳地址不带 /login）：先带到登录页换 token，别被守卫冲掉
  if ((to.query.authCode || to.query.code) && to.path !== "/login") {
    return next({ path: "/login", query: { ...to.query } });
  }

  // 登录页放行
  if (to.path === "/login") {
    if (store.isLoggedIn) return next("/");
    return next();
  }

  // 需要登录的页面
  if (to.meta.requiresAuth) {
    if (!store.isLoggedIn) {
      // 尝试从 localStorage 恢复
      const token = localStorage.getItem("wo_token");
      if (token) {
        try {
          const user = await getMe();
          store.setAuth(token, user);
          store.permissions = await getPermissions();
          return next();
        } catch {
          store.logout();
        }
      }
      return next(`/login?redirect=${to.path}`);
    }

    // 确保权限配置已加载（登录后正常路径已加载；此处兜底一次）
    if (!store.permissions) {
      try {
        store.permissions = await getPermissions();
      } catch {
        /* 加载失败保持 fail-open */
      }
    }

    // admin 超管恒放行
    if (store.isAdmin) return next();

    // 工单详情对已登录用户放行（详情不在菜单权限里）
    if (to.path.startsWith("/work-orders/")) return next();

    // 根路径重定向到第一个有权限的菜单
    if (to.path === "/" || to.path === "") {
      const first = firstAccessibleMenu();
      if (!first) {
        store.logout();
        return next("/login");
      }
      return next(first);
    }

    // 其余按已保存的菜单权限配置判断
    const menu = findMenuByPath(to.path);
    if (menu && store.canAccessMenu(menu.group, menu.title)) return next();

    const failover = firstAccessibleMenu();
    if (!failover) {
      store.logout();
      return next("/login");
    }
    return next(failover);
  }

  next();
});

// 取第一个当前角色可访问的菜单路径；无任何权限时返回 null
function firstAccessibleMenu(): string | null {
  const store = useUserStore();
  for (const g of MENU_GROUPS) {
    for (const item of g.items) {
      if (store.canAccessMenu(g.label, item.title)) return item.path;
    }
  }
  return null;
}

export default router;
