<template>
  <div class="users-page">
    <div class="header">
      <div><h1>用户管理</h1><div class="meta">角色分配 · 权限配置 · 菜单可见性</div></div>
    </div>

    <div class="grid2">
      <!-- 用户列表 -->
      <div class="card">
        <div class="card-hd">
          <h3>用户列表</h3>
          <div class="hd-tools">
            <t-input
              v-model="searchText"
              placeholder="搜索姓名 / 钉钉ID"
              clearable
              size="small"
              class="search-box"
              @change="onSearchInput"
            />
            <span class="count">{{ total }} 人</span>
          </div>
        </div>
        <div class="card-body">
        <PageError v-if="loadError" title="用户加载失败" :message="loadError" @action="loadUsers" />
        <t-table v-else
          :data="users"
          :columns="columns"
          row-key="id"
          :loading="loadingUsers"
          :pagination="pagination"
          @page-change="onPageChange"
          size="small"
          cell-empty-content="—"
          hover
        >
          <template #name="{ row }"><b>{{ row.name }}</b></template>
          <template #role="{ row }">
            <t-select v-model="row.role" :options="roleOptions" size="small" style="width:110px" @change="changeRole(row)" />
          </template>
          <template #dingtalk_id="{ row }"><span class="muted">{{ row.dingtalk_id ? row.dingtalk_id.slice(0, 12) + '…' : '—' }}</span></template>
          <template #status="{ row }">
            <t-tag :theme="row.is_active ? 'success' : 'danger'" size="small" variant="light">{{ row.is_active ? '启用' : '禁用' }}</t-tag>
          </template>
          <template #action="{ row }">
            <t-button size="small" variant="outline" @click="toggleActive(row)">{{ row.is_active ? '禁用' : '启用' }}</t-button>
          </template>
        </t-table>
        </div>
      </div>

      <!-- 权限配置 -->
      <div class="card">
        <div class="card-hd"><h3>菜单权限配置</h3><span class="count">按角色分配</span></div>
        <div class="card-body perm-grid">
          <div v-for="group in permissionConfig" :key="group.label" class="perm-group">
            <div class="perm-group-label">{{ group.label }}</div>
            <div v-for="item in group.items" :key="item.title" class="perm-row">
              <span class="perm-title">{{ item.title }}</span>
              <div class="perm-roles">
                <label v-for="role in ['admin', 'approver', 'executor', 'readonly']" :key="role" class="perm-check">
                  <input type="checkbox" :checked="hasPerm(item, role)" @change="togglePerm(item, role)" />
                  {{ roleLabel(role) }}
                </label>
              </div>
            </div>
          </div>
        </div>
        <div class="form-actions">
          <button class="btn btn-pri" @click="savePermissions" :disabled="saving">
            {{ saving ? '保存中…' : '保存权限配置' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { toast } from "@/utils/feedback";
import { onMounted, onUnmounted, reactive, ref } from "vue";
import { useUserStore } from "@/stores/user";
import http from "@/api/http";
import { getPermissions, savePermissions as savePermissionsApi } from "@/api/auth";
import PageError from "@/components/PageError.vue";

defineOptions({ name: "UserManagement" });

const store = useUserStore();
const users = ref<any[]>([]);
const total = ref(0);
const searchText = ref("");
const loadingUsers = ref(false);
const loadError = ref("");
let loadSeq = 0;
let searchTimer: ReturnType<typeof setTimeout> | null = null;
// 用户管理保持固定 12 行，避免分页尺寸切换导致左右面板高度跳变。
const pagination = reactive({ current: 1, pageSize: 12, total: 0, showJumper: true, showPageSize: false });
const saving = ref(false);
const roleOptions = [
  { label: "管理员", value: "admin" },
  { label: "审批人", value: "approver" },
  { label: "责任人", value: "executor" },
  { label: "只读", value: "readonly" },
];
const columns: any[] = [
  { colKey: "name", title: "姓名", width: 100 },
  { colKey: "role", title: "角色", width: 130 },
  { colKey: "dingtalk_id", title: "钉钉ID", width: 130, ellipsis: true },
  { colKey: "status", title: "状态", width: 80 },
  { colKey: "action", title: "操作", width: 90 },
];

interface PermItem {
  title: string;
  roles: string[];
}
interface PermGroup {
  label: string;
  items: PermItem[];
}

const permissionConfig = reactive<PermGroup[]>([
  {
    label: "工作台",
    items: [
      { title: "管理看板", roles: ["admin", "approver"] },
      { title: "我的工单", roles: ["admin", "approver", "executor"] },
    ],
  },
  {
    label: "工单管理",
    items: [
      { title: "工单列表", roles: ["admin", "approver"] },
      { title: "新建工单", roles: ["admin", "approver"] },
      { title: "闭环记录", roles: ["admin", "approver", "executor"] },
    ],
  },
  {
    label: "基础数据",
    items: [
      { title: "项目管理", roles: ["admin", "approver"] },
      { title: "用户管理", roles: ["admin"] },
      // 数据池仍是自动同步的内部暂存层；日常不开放人工入口，需恢复时取消本行注释。
      // { title: "数据池", roles: ["admin", "approver"] },
      { title: "SOP知识库", roles: ["admin", "approver", "executor"] },
    ],
  },
  {
    label: "系统设置",
    items: [
      { title: "规则配置", roles: ["admin"] },
      { title: "操作日志", roles: ["admin"] },
      { title: "钉钉集成", roles: ["admin", "approver"] },
    ],
  },
]);

function roleLabel(r: string) {
  return { admin: "管理员", approver: "审批人", executor: "责任人", readonly: "只读" }[r] || r;
}

function hasPerm(item: PermItem, role: string) {
  return item.roles.includes(role);
}

function togglePerm(item: PermItem, role: string) {
  if (item.roles.includes(role)) {
    item.roles = item.roles.filter((r) => r !== role);
  } else {
    item.roles.push(role);
  }
}

async function savePermissions() {
  saving.value = true;
  try {
    // 构建权限配置（只提交菜单权限，actions 由后端保留既有值）
    const menu_groups: Record<string, Record<string, { roles: string[] }>> = {};
    for (const g of permissionConfig) {
      menu_groups[g.label] = {};
      for (const item of g.items) {
        menu_groups[g.label][item.title] = { roles: [...item.roles] };
      }
    }
    // 持久化到后端，并更新 store（全站菜单据此过滤）
    const saved = await savePermissionsApi({ menu_groups });
    store.permissions = saved;
    toast.success("菜单权限已保存并全局生效");
  } catch (e: any) {
    toast.error("保存失败：" + e.message);
  } finally {
    saving.value = false;
  }
}

// 打开页面时用已保存的权限回填复选框，避免展示默认值覆盖线上配置
function syncPermissionConfig() {
  const perms = store.permissions;
  if (!perms?.menu_groups) return;
  for (const g of permissionConfig) {
    const saved = perms.menu_groups[g.label];
    if (!saved) continue;
    for (const item of g.items) {
      const conf = saved[item.title];
      if (conf && Array.isArray(conf.roles)) item.roles = [...conf.roles];
    }
  }
}

async function changeRole(u: any) {
  try {
    await http.patch(`/auth/users/${u.id}/role`, { role: u.role });
  } catch (e: any) {
    toast.error("修改失败：" + e.message);
    await loadUsers();
  }
}

async function toggleActive(u: any) {
  try {
    const res = await http.patch<any, any>(`/auth/users/${u.id}/toggle-active`);
    u.is_active = res.is_active;
  } catch (e: any) {
    toast.error("操作失败：" + e.message);
  }
}

async function loadUsers() {
  const seq = ++loadSeq;
  loadingUsers.value = true;
  loadError.value = "";
  try {
    const params: Record<string, any> = { page: pagination.current, page_size: pagination.pageSize };
    if (searchText.value.trim()) params.q = searchText.value.trim();
    const res: any = await http.get("/auth/users", { params });
    if (seq !== loadSeq) return;
    users.value = res.items || [];
    total.value = res.total || 0;
    pagination.total = res.total || 0;
  } catch (e: any) {
    if (seq === loadSeq) loadError.value = e.message || "请稍后重试";
  } finally {
    if (seq === loadSeq) loadingUsers.value = false;
  }
}
function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer);
  searchTimer = setTimeout(doSearch, 300);
}
function doSearch() {
  if (searchTimer) clearTimeout(searchTimer);
  pagination.current = 1;
  loadUsers();
}
function onPageChange(p: any) {
  pagination.current = p.current;
  loadUsers();
}

onMounted(async () => {
  loadUsers();
  if (!store.permissions) {
    try {
      store.permissions = await getPermissions();
    } catch {
      /* 权限加载失败不影响使用 */
    }
  }
  syncPermissionConfig();
});
onUnmounted(() => { if (searchTimer) clearTimeout(searchTimer); });
</script>

<style scoped>
.users-page .header { margin-bottom: 20px; }
.header h1 { font-size: var(--fs-h1); font-weight: 700; }
.meta { font-size: 12px; color: var(--muted); }

.grid2 { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 440px); gap: 20px; align-items: start; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); display: flex; flex-direction: column; }
.card-body { overflow-x: auto; }
.card-hd { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; border-bottom: 1px solid var(--border); flex: none; }
.card-hd h3 { font-size: 15px; font-weight: 700; }
.hd-tools { display: flex; align-items: center; gap: 12px; }
.search-box { width: 200px; }
.count { font-size: 12px; color: var(--muted); }

.muted { color: var(--muted); font-size: 12px; }

.perm-grid { padding: 16px 20px; }
.perm-group { margin-bottom: 16px; }
.perm-group-label { font-size: 13px; font-weight: 700; color: var(--brand); margin-bottom: 8px; padding-bottom: 4px; border-bottom: 1px solid var(--border); }
.perm-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 6px 0; }
.perm-title { font-size: 13px; }
.perm-roles { display: flex; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }
.perm-check { display: flex; align-items: center; gap: 3px; font-size: 11px; color: var(--muted); cursor: pointer; white-space: nowrap; }
.perm-check input { margin: 0; }

.form-actions { display: flex; justify-content: flex-end; padding: 12px 20px; border-top: 1px solid var(--border); }

@media (max-width: 1200px) { .grid2 { grid-template-columns: 1fr; } }
</style>
