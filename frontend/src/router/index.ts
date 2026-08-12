import { createRouter, createWebHistory } from "vue-router";
import { useUserStore } from "@/stores/user";

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
          const { getMe, getPermissions } = await import("@/api/auth");
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

    // 权限检查：管理员和审批人可以访问所有页面
    if (store.isAdmin || store.isApprover) return next();

    // executor 只能访问我的工单、工单详情、闭环记录
    const allowedPaths = ["/my", "/closed"];
    if (to.path.startsWith("/work-orders/")) return next(); // 工单详情
    if (allowedPaths.includes(to.path)) return next();
    if (to.path === "/" || to.path === "") return next("/my"); // 重定向到我的工单

    // 其他页面拒绝
    return next("/my");
  }

  next();
});

export default router;