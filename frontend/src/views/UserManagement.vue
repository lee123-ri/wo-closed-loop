<template>
  <div class="users-page">
    <div class="header">
      <div><h1>用户管理</h1><div class="meta">角色分配 · 权限配置 · 菜单可见性</div></div>
    </div>

    <div class="grid2">
      <!-- 用户列表 -->
      <div class="card">
        <div class="card-hd"><h3>用户列表</h3><span class="count">{{ total }} 人</span></div>
        <table>
          <thead>
            <tr>
              <th>姓名</th>
              <th>角色</th>
              <th>钉钉ID</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="u in users" :key="u.id" :class="{ inactive: !u.is_active }">
              <td><b>{{ u.name }}</b></td>
              <td>
                <select v-model="u.role" @change="changeRole(u)" class="role-select">
                  <option value="admin">管理员</option>
                  <option value="approver">审批人</option>
                  <option value="executor">责任人</option>
                  <option value="readonly">只读</option>
                </select>
              </td>
              <td class="muted">{{ u.dingtalk_id ? u.dingtalk_id.slice(0, 12) + '…' : '—' }}</td>
              <td>
                <span class="tag" :class="u.is_active ? 'tag-green' : 'tag-red'">
                  {{ u.is_active ? '启用' : '禁用' }}
                </span>
              </td>
              <td>
                <button class="btn btn-sm btn-out" @click="toggleActive(u)">
                  {{ u.is_active ? '禁用' : '启用' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      <div class="pagination" v-if="total > pageSize">
        <button class="btn btn-sm btn-out" @click="prevPage" :disabled="page <= 1">‹ 上一页</button>
        <span class="page-info">{{ page }} / {{ Math.ceil(total / pageSize) }}</span>
        <button class="btn btn-sm btn-out" @click="nextPage" :disabled="page * pageSize >= total">下一页 ›</button>
      </div>
      </div>

      <!-- 权限配置 -->
      <div class="card">
        <div class="card-hd"><h3>菜单权限配置</h3><span class="count">按角色分配</span></div>
        <div class="perm-grid">
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
import { onMounted, reactive, ref } from "vue";
import { useUserStore } from "@/stores/user";
import http from "@/api/http";

const store = useUserStore();
const users = ref<any[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = 50;
const saving = ref(false);

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
    label: "数据管理",
    items: [
      { title: "数据池", roles: ["admin", "approver"] },
    ],
  },
  {
    label: "系统设置",
    items: [
      { title: "用户管理", roles: ["admin"] },
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
    // 构建权限配置
    const menuGroups: Record<string, any> = {};
    for (const g of permissionConfig) {
      menuGroups[g.label] = {};
      for (const item of g.items) {
        menuGroups[g.label][item.title] = { roles: item.roles };
      }
    }
    // 更新 store 和调用后端
    store.permissions = {
      roles: ["admin", "approver", "executor", "readonly"],
      menu_groups: menuGroups,
      actions: store.permissions?.actions || {},
    };
    alert("权限配置已更新（当前会话生效）");
  } finally {
    saving.value = false;
  }
}

async function changeRole(u: any) {
  try {
    await http.patch(`/auth/users/${u.id}/role`, { role: u.role });
  } catch (e: any) {
    alert("修改失败：" + e.message);
    await loadUsers();
  }
}

async function toggleActive(u: any) {
  try {
    const res = await http.patch(`/auth/users/${u.id}/toggle-active`);
    u.is_active = res.is_active;
  } catch (e: any) {
    alert("操作失败：" + e.message);
  }
}

async function loadUsers() {
  try {
    const res: any = await http.get(`/auth/users?page=${page.value}&page_size=${pageSize}`);
    users.value = res.items || [];
    total.value = res.total || 0;
  } catch (e: any) { console.error(e); }
}
function prevPage() { if (page.value > 1) { page.value--; loadUsers(); } }
function nextPage() { if (page.value * pageSize < total.value) { page.value++; loadUsers(); } }

onMounted(loadUsers);
</script>

<style scoped>
.users-page .header { margin-bottom: 20px; }
.header h1 { font-size: var(--fs-h1); font-weight: 700; }
.meta { font-size: 12px; color: var(--muted); }

.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.card { background: var(--card); border-radius: var(--radius); box-shadow: var(--shadow); overflow: auto; }
.card-hd { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; border-bottom: 1px solid var(--border); }
.card-hd h3 { font-size: 15px; font-weight: 700; }
.count { font-size: 12px; color: var(--muted); }

table { width: 100%; border-collapse: collapse; }
th, td { padding: 10px 12px; text-align: left; font-size: 13px; border-bottom: 1px solid var(--border); }
th { background: #f8fafc; font-weight: 600; font-size: 11px; color: var(--muted); }
tr.inactive { opacity: 0.5; }
.muted { color: var(--muted); font-size: 12px; }
.role-select { padding: 4px 8px; border: 1px solid var(--border); border-radius: 4px; font-size: 12px; }

.perm-grid { padding: 16px 20px; }
.perm-group { margin-bottom: 16px; }
.perm-group-label { font-size: 13px; font-weight: 700; color: var(--brand); margin-bottom: 8px; padding-bottom: 4px; border-bottom: 1px solid var(--border); }
.perm-row { display: flex; align-items: center; justify-content: space-between; padding: 6px 0; }
.perm-title { font-size: 13px; }
.perm-roles { display: flex; gap: 10px; }
.perm-check { display: flex; align-items: center; gap: 3px; font-size: 11px; color: var(--muted); cursor: pointer; }
.perm-check input { margin: 0; }

.form-actions { display: flex; justify-content: flex-end; padding: 12px 20px; border-top: 1px solid var(--border); }

.tag { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; }
.tag-green { background: #ecfdf5; color: var(--green); }
.tag-red { background: #fef2f2; color: var(--red); }

.btn { padding: 8px 16px; border-radius: 6px; border: none; cursor: pointer; font-size: 13px; font-weight: 600; }
.btn-pri { background: var(--brand); color: #fff; }
.btn-pri:disabled { opacity: 0.6; }
.btn-out { background: #fff; color: #4b5563; border: 1px solid var(--border); }
.btn-sm { padding: 4px 10px; font-size: 11px; }
.pagination { display: flex; justify-content: center; align-items: center; gap: 10px; padding: 12px 0; }
.page-info { font-size: 12px; color: var(--muted); }

@media (max-width: 900px) { .grid2 { grid-template-columns: 1fr; } }
</style>