<template>
  <div class="page">
    <div class="header"><h1>项目管理</h1><div class="meta">场站/项目的新增与管理</div></div>
    <div class="card">
      <div class="card-hd">
        <h3>项目列表</h3>
        <t-space>
          <t-button theme="default" variant="outline" :loading="syncing" @click="syncLedger">从 OA 同步项目</t-button>
          <t-button theme="primary" @click="openCreate">＋ 新增项目</t-button>
        </t-space>
      </div>
      <div v-if="syncNote" class="sync-note">{{ syncNote }}</div>
      <PageError v-if="loadError" title="项目加载失败" :message="loadError" @action="load" />
      <t-table v-else
        :data="pagedProjects"
        :columns="columns"
        row-key="id"
        hover
        size="small"
        :loading="loading"
        cell-empty-content="—"
      >
        <template #code="{ row }">
          <span class="code">{{ row.code }}</span>
        </template>
        <template #name="{ row }">
          <b>{{ row.name }}</b>
        </template>
        <template #type="{ row }">
          {{ typeLabel(row.type) }}
        </template>
        <template #region="{ row }">
          {{ row.region || '—' }}
        </template>
        <template #status="{ row }">
          <span class="tag" :class="row.is_active ? 'tag-green' : 'tag-red'">{{ row.is_active ? '启用' : '停用' }}</span>
        </template>
        <template #action="{ row }">
          <t-button size="small" variant="outline" @click="editProject(row)">编辑</t-button>
        </template>
      </t-table>
      <div v-if="!loadError" class="pagination-bar">
        <t-pagination
          v-model:current="page"
          v-model:pageSize="pageSize"
          :total="total"
          :page-size-options="[10, 20, 50]"
          show-page-size
          show-jumper
          @change="onPageChange"
        />
      </div>
    </div>
    <t-dialog v-model:visible="showForm" :header="(editing ? '编辑' : '新增') + '项目'" width="480" :footer="false">
      <div class="modal-body">
          <div class="form-group" v-if="editing"><label>项目编码</label><t-input :value="editing.code" disabled /></div>
          <div class="form-hint" v-else>项目编码由系统自动分配（PRJ-####），无需手工填写</div>
          <div class="form-group"><label>项目名称 <span class="required">*</span></label><t-input v-model="form.name" placeholder="输入项目名称" /></div>
          <div class="form-group"><label>类型</label><t-select v-model="form.type" :options="typeOptions" /></div>
          <div class="form-group"><label>区域 <span class="required">*</span></label><t-select v-model="form.region" placeholder="选择七大区" :options="regionOptions" /></div>
          <div class="form-actions"><t-button variant="outline" @click="closeForm">取消</t-button><t-button theme="primary" :loading="saving" @click="save">保存</t-button></div>
        </div>
    </t-dialog>
  </div>
</template>
<script setup lang="ts">
import { toast } from "@/utils/feedback";
import { computed, onMounted, reactive, ref, watch } from "vue";
import http from "@/api/http";
import PageError from "@/components/PageError.vue";
const REGIONS = ["华北", "华中", "华东", "华南", "西北", "西南", "东北"];
const regionOptions = REGIONS.map((r) => ({ value: r, label: r }));
const typeOptions = [
  { value: "wind", label: "风电" }, { value: "pv", label: "光伏" },
  { value: "storage", label: "储能" }, { value: "", label: "其他" },
];

defineOptions({ name: "ProjectManage" });

const allProjects = ref<any[]>([]);
const loading = ref(false);
const loadError = ref("");
const page = ref(1);
const pageSize = ref(10);
const showForm = ref(false);
const editing = ref<any>(null);
const saving = ref(false);
const form = reactive({ name: "", type: "", region: "" });
const syncing = ref(false);
const syncNote = ref("");

const columns = [
  { colKey: "code", title: "编码", width: 120 },
  { colKey: "name", title: "名称", minWidth: 200, ellipsis: true },
  { colKey: "type", title: "类型", width: 100 },
  { colKey: "region", title: "区域", width: 120 },
  { colKey: "status", title: "状态", width: 80 },
  { colKey: "action", title: "操作", width: 80 },
];

const total = computed(() => allProjects.value.length);
// 按「编码」排序：PRJ-0001 起顺序排，翻到第一页即以最小编码开头（用户口径：编号正常、第一页从 001 开始）
const sortedProjects = computed(() =>
  [...allProjects.value].sort((a, b) => String(a.code || "").localeCompare(String(b.code || ""), undefined, { numeric: true }))
);
const pagedProjects = computed(() => {
  const start = (page.value - 1) * pageSize.value;
  return sortedProjects.value.slice(start, start + pageSize.value);
});

function typeLabel(t: string) { return { wind: "风电", pv: "光伏", storage: "储能" }[t] || t || "—"; }
async function load() {
  loading.value = true;
  loadError.value = "";
  try {
    allProjects.value = await http.get("/config/projects/all");
  } catch (e: any) { loadError.value = e.message || "请稍后重试"; }
  finally { loading.value = false; }
}
function onPageChange(p: any) {
  page.value = p.pageSize !== pageSize.value ? 1 : p.current;
  pageSize.value = p.pageSize;
}
function resetForm() { editing.value = null; form.name = ""; form.type = ""; form.region = ""; }
function openCreate() { resetForm(); showForm.value = true; }
function closeForm() { showForm.value = false; resetForm(); }
function editProject(p: any) { editing.value = p; form.name = p.name; form.type = p.type || ""; form.region = p.region || ""; showForm.value = true; }
async function save() {
  if (saving.value) return;
  if (!form.name.trim()) { toast.warning("请填写项目名称"); return; }
  if (!REGIONS.includes(form.region)) { toast.warning("请选择七大区中的区域"); return; }
  saving.value = true;
  try {
    if (editing.value) await http.patch(`/config/projects/${editing.value.id}`, { name: form.name, type: form.type || null, region: form.region || null });
    else await http.post("/config/projects", { name: form.name, type: form.type || null, region: form.region || null });
    closeForm();
    await load();
  } catch (e: any) { toast.error(e.message); }
  finally { saving.value = false; }
}
async function syncLedger() {
  syncing.value = true;
  syncNote.value = "";
  try {
    const r = await http.post<any, any>("/config/projects/sync-ledger");
    const errs = r.errors || [];
    if (errs.length) {
      syncNote.value = `同步未完成（${errs.length} 处问题）：${errs[0]}`;
      toast.warning(errs[0]);
    } else {
      syncNote.value = `同步完成：新增 ${r.synced} 个项目${r.updated ? `，更新 ${r.updated} 个` : ""}${r.disabled ? `，停用 ${r.disabled} 个` : ""}（过滤状态：${(r.active_statuses || []).join("、")}）`;
      toast.success(`已同步：新增 ${r.synced} 个项目`);
    }
    await load();
  } catch (e: any) {
    syncNote.value = "";
    toast.error("同步失败：" + (e.message || "未知错误"));
  } finally {
    syncing.value = false;
  }
}
onMounted(load);
watch(showForm, (visible) => { if (!visible) resetForm(); });
</script>
<style scoped>
.page .header { margin-bottom: 20px; } .header h1 { font-size: var(--fs-h1); font-weight: 700; } .meta { font-size: 12px; color: var(--muted); }
.card { background: var(--card); border-radius: var(--radius); box-shadow: var(--shadow); overflow: auto; }
.card-hd { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; border-bottom: 1px solid var(--border); }
.card-hd h3 { font-size: 15px; font-weight: 700; }
.sync-note { padding: 8px 20px; font-size: 12px; color: var(--muted); background: #f8fafc; border-bottom: 1px solid var(--border); }
table { width: 100%; border-collapse: collapse; } th, td { padding: 10px 12px; text-align: left; font-size: 13px; border-bottom: 1px solid var(--border); }
th { background: #f8fafc; font-weight: 600; font-size: 11px; color: var(--muted); } .code { font-family: monospace; font-size: 12px; color: var(--muted); }
.tag { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; }
.tag-green { background: #ecfdf5; color: var(--green); } .tag-red { background: #fef2f2; color: var(--red); }
.modal-body { padding: 20px; } .form-group { margin-bottom: 12px; } .form-group label { display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px; }
.form-hint { font-size: 12px; color: var(--muted); background: #f8fafc; border: 1px dashed var(--border); border-radius: 6px; padding: 8px 10px; margin-bottom: 12px; }
.form-group :deep(.t-input), .form-group :deep(.t-select) { width: 100%; }
.required { color: var(--red); }
.form-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.pagination-bar { display: flex; justify-content: center; padding: 16px 0 0; }
</style>
