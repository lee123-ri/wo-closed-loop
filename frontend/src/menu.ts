// 全站菜单定义：MainLayout 渲染 + 路由守卫权限判断共用，避免两处漂移。

export interface MenuItem {
  path: string;
  icon: string;
  title: string;
}

export interface MenuGroup {
  label: string;
  icon: string;
  items: MenuItem[];
}

export const MENU_GROUPS: MenuGroup[] = [
  {
    label: "工作台",
    icon: "dashboard",
    items: [
      { path: "/", icon: "dashboard", title: "管理看板" },
      { path: "/my", icon: "user", title: "我的工单" },
    ],
  },
  {
    label: "工单管理",
    icon: "task",
    items: [
      { path: "/work-orders", icon: "view-list", title: "工单列表" },
      { path: "/create", icon: "add-circle", title: "新建工单" },
      { path: "/closed", icon: "check-circle", title: "闭环记录" },
    ],
  },
  {
    label: "基础数据",
    icon: "data-base",
    items: [
      { path: "/projects", icon: "folder", title: "项目管理" },
      { path: "/users", icon: "usergroup", title: "用户管理" },
      { path: "/pool", icon: "layers", title: "数据池" },
      { path: "/sop", icon: "book-open", title: "SOP知识库" },
    ],
  },
  {
    label: "系统设置",
    icon: "setting",
    items: [
      { path: "/config", icon: "setting", title: "规则配置" },
      { path: "/audit-log", icon: "system-log", title: "操作日志" },
      { path: "/dingtalk", icon: "chat", title: "钉钉集成" },
    ],
  },
];

/** 全量扁平菜单项（activeMenu / 面包屑用） */
export const FLAT_MENUS: MenuItem[] = MENU_GROUPS.flatMap((g) => g.items);

/** 按路径定位菜单项所属分组与标题，供权限判断用 */
export function findMenuByPath(path: string): { group: string; title: string } | null {
  for (const g of MENU_GROUPS) {
    for (const it of g.items) {
      if (it.path === path) return { group: g.label, title: it.title };
    }
  }
  return null;
}
