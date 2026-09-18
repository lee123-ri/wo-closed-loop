<template>
  <div class="users-page">
    <div class="header">
      <div><h1>用户管理</h1><div class="meta">钉钉部门带入 · 系统身份 · 业务岗位分配</div></div>
    </div>

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
          <template #department="{ row }"><span>{{ row.department || '未同步' }}</span></template>
          <template #business_roles="{ row }">
            <div class="role-tags">
              <t-tag v-for="role in row.business_roles" :key="role.code" size="small" theme="primary" variant="light">{{ role.name }}</t-tag>
              <span v-if="!row.business_roles?.length" class="muted">未分配</span>
            </div>
          </template>
          <template #dingtalk_id="{ row }"><span class="muted">{{ row.dingtalk_id ? row.dingtalk_id.slice(0, 12) + '…' : '—' }}</span></template>
          <template #status="{ row }">
            <t-tag :theme="row.is_active ? 'success' : 'danger'" size="small" variant="light">{{ row.is_active ? '启用' : '禁用' }}</t-tag>
          </template>
          <template #action="{ row }">
            <t-space :size="4"><t-button size="small" variant="outline" @click="openEdit(row)">编辑</t-button><t-button size="small" variant="outline" @click="toggleActive(row)">{{ row.is_active ? '禁用' : '启用' }}</t-button></t-space>
          </template>
        </t-table>
        </div>
      </div>

    <t-dialog v-model:visible="editDialog.open" :header="`编辑用户：${editDialog.name}`" width="480" :footer="false">
      <div class="form-group"><label>钉钉部门</label><input v-model="editDialog.department" placeholder="钉钉同步后可按实际归属修正" /><div class="form-hint">默认取钉钉通讯录；修改只影响本平台资料，不会回写钉钉。</div></div>
      <div class="form-group"><label>业务岗位</label><t-select v-model="editDialog.roleCodes" :options="businessRoleSelectOptions" multiple clearable filterable placeholder="默认：项目人员（仅本人相关）" /><div class="form-hint">未选择时自动按“项目人员”处理；岗位定义和数据权限在“规则配置”维护，此处只分配给人员。</div></div>
      <div class="modal-actions"><t-button variant="outline" @click="editDialog.open = false">取消</t-button><t-button theme="primary" :loading="savingProfile" @click="saveProfile">保存</t-button></div>
    </t-dialog>
  </div>
</template>

<script setup lang="ts">
import { toast } from "@/utils/feedback";
import { computed, onMounted, onUnmounted, reactive, ref } from "vue";
import http from "@/api/http";
import PageError from "@/components/PageError.vue";

defineOptions({ name: "UserManagement" });

const users = ref<any[]>([]);
const total = ref(0);
const searchText = ref("");
const loadingUsers = ref(false);
const loadError = ref("");
let loadSeq = 0;
let searchTimer: ReturnType<typeof setTimeout> | null = null;
// 用户管理保持固定 14 行，避免分页尺寸切换导致左右面板高度跳变。
const pagination = reactive({ current: 1, pageSize: 14, total: 0, showJumper: true, showPageSize: false });
const savingProfile = ref(false);
const businessRoleOptions = ref<any[]>([]);
const businessRoleSelectOptions = computed(() => businessRoleOptions.value.filter((item) => item.is_active).map((item) => ({ label: item.name, value: item.code })));
const editDialog = reactive({ open: false, id: 0, name: "", department: "", roleCodes: [] as string[] });
const roleOptions = [
  { label: "管理员", value: "admin" },
  { label: "审批人", value: "approver" },
  { label: "执行人", value: "executor" },
];
const columns: any[] = [
  { colKey: "name", title: "姓名", width: 100 },
  { colKey: "role", title: "系统身份", width: 130 },
  { colKey: "department", title: "钉钉部门", width: 160, ellipsis: true },
  { colKey: "business_roles", title: "业务岗位", minWidth: 180 },
  { colKey: "dingtalk_id", title: "钉钉ID", width: 130, ellipsis: true },
  { colKey: "status", title: "状态", width: 80 },
  { colKey: "action", title: "操作", width: 150 },
];

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

function openEdit(u: any) {
  editDialog.id = u.id;
  editDialog.name = u.name;
  editDialog.department = u.department || "";
  editDialog.roleCodes = (u.business_roles || []).map((role: any) => role.code);
  editDialog.open = true;
}

async function saveProfile() {
  savingProfile.value = true;
  try {
    const [profile, businessRoles] = await Promise.all([
      http.patch<any, any>(`/auth/users/${editDialog.id}/profile`, { department: editDialog.department }),
      http.put<any, any>(`/auth/users/${editDialog.id}/business-roles`, { role_codes: editDialog.roleCodes }),
    ]);
    const row = users.value.find((user) => user.id === editDialog.id);
    if (row) Object.assign(row, profile, { business_roles: businessRoles.business_roles });
    editDialog.open = false;
    toast.success("用户资料和业务岗位已保存");
  } catch (e: any) {
    toast.error("保存失败：" + (e.message || "请稍后重试"));
  } finally {
    savingProfile.value = false;
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
  try { businessRoleOptions.value = await http.get("/auth/business-roles"); }
  catch { toast.warning("业务岗位选项加载失败，请稍后重试"); }
});
onUnmounted(() => { if (searchTimer) clearTimeout(searchTimer); });
</script>

<style scoped>
.users-page .header { margin-bottom: 20px; }
.header h1 { font-size: var(--fs-h1); font-weight: 700; }
.meta { font-size: 12px; color: var(--muted); }

.card { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); display: flex; flex-direction: column; }
.card-body { overflow-x: auto; }
.card-hd { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; border-bottom: 1px solid var(--border); flex: none; }
.card-hd h3 { font-size: 15px; font-weight: 700; }
.hd-tools { display: flex; align-items: center; gap: 12px; }
.search-box { width: 200px; }
.count { font-size: 12px; color: var(--muted); }

.muted { color: var(--muted); font-size: 12px; }
.role-tags { display: flex; gap: 4px; flex-wrap: wrap; }
.form-group { margin-bottom: 16px; }
.form-group label { display: block; font-size: 13px; font-weight: 600; margin-bottom: 6px; }
.form-group input[type="text"], .form-group > input { width: 100%; padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; }
.form-hint { margin-top: 5px; color: var(--muted); font-size: 12px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 20px; }

</style>
