<template>
  <div class="page">
    <div class="header"><h1>项目管理</h1><div class="meta">场站/项目的新增与管理</div></div>
    <div class="card">
      <div class="card-hd"><h3>项目列表</h3><button class="btn btn-pri btn-sm" @click="showForm = true">+ 新增项目</button></div>
      <t-table
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
        <template #product_series="{ row }">
          {{ row.product_series || '—' }}
        </template>
        <template #entry_date="{ row }">
          {{ row.entry_date || '—' }}
        </template>
        <template #judgment_date="{ row }">
          {{ row.judgment_date || '—' }}
        </template>
        <template #judgment="{ row }">
          <span v-if="row.judgment_status === 'created'" class="tag tag-green">已建会</span>
          <span v-else-if="row.judgment_status === 'failed'" class="tag tag-red" :title="row.judgment_error">失败</span>
          <span v-else-if="row.entry_date" class="tag tag-amber">待建</span>
          <span v-else>—</span>
        </template>
        <template #status="{ row }">
          <span class="tag" :class="row.is_active ? 'tag-green' : 'tag-red'">{{ row.is_active ? '启用' : '停用' }}</span>
        </template>
        <template #action="{ row }">
          <button class="btn btn-sm btn-out" @click="editProject(row)">编辑</button>
        </template>
      </t-table>
      <div class="pagination-bar">
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
    <div v-if="showForm" class="modal-overlay" @click.self="showForm = false">
      <div class="modal"><div class="modal-hd"><h3>{{ editing ? '编辑' : '新增' }}项目</h3><button class="btn-close" @click="showForm = false">✕</button></div>
        <div class="modal-body">
          <div class="form-group"><label>项目编码</label><input v-model="form.code" :disabled="!!editing" /></div>
          <div class="form-group"><label>项目名称</label><input v-model="form.name" /></div>
          <div class="form-group"><label>类型</label><select v-model="form.type"><option value="wind">风电</option><option value="pv">光伏</option><option value="storage">储能</option><option value="">其他</option></select></div>
          <div class="form-group"><label>区域</label><select v-model="form.region"><option value="">未指定</option><option v-for="r in REGIONS" :key="r" :value="r">{{ r }}</option></select></div>
          <div class="form-group"><label>产品系列</label><select v-model="form.product_series"><option value="">未指定</option><option v-for="s in SERIES" :key="s" :value="s">{{ s }}</option></select></div>
          <div class="form-group"><label>入场日期</label><input type="date" v-model="form.entry_date" /></div>
          <div class="form-actions"><button class="btn btn-out" @click="showForm = false">取消</button><button class="btn btn-pri" @click="save" :disabled="saving">{{ saving ? '保存中' : '保存' }}</button></div>
        </div>
      </div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import http from "@/api/http";
const REGIONS = ["华北", "华中", "华东", "华南", "西北", "西南", "东北"];
const SERIES = ["HS100", "HS200", "HS300", "HS400", "HS500", "500Pro"];
const allProjects = ref<any[]>([]);
const loading = ref(false);
const page = ref(1);
const pageSize = ref(10);
const showForm = ref(false);
const editing = ref<any>(null);
const saving = ref(false);
const form = reactive({ code: "", name: "", type: "", region: "", entry_date: "", product_series: "" });

const columns = [
  { colKey: "code", title: "编码", width: 110 },
  { colKey: "name", title: "名称", minWidth: 200, ellipsis: true },
  { colKey: "type", title: "类型", width: 80 },
  { colKey: "region", title: "区域", width: 90 },
  { colKey: "product_series", title: "产品系列", width: 90 },
  { colKey: "entry_date", title: "入场日期", width: 105 },
  { colKey: "judgment_date", title: "判定日", width: 105 },
  { colKey: "judgment", title: "判定会", width: 80 },
  { colKey: "status", title: "状态", width: 70 },
  { colKey: "action", title: "操作", width: 80 },
];

const total = computed(() => allProjects.value.length);
const pagedProjects = computed(() => {
  const start = (page.value - 1) * pageSize.value;
  return allProjects.value.slice(start, start + pageSize.value);
});

function typeLabel(t: string) { return { wind: "风电", pv: "光伏", storage: "储能" }[t] || t || "—"; }
async function load() {
  loading.value = true;
  try {
    allProjects.value = await http.get("/config/projects/all");
  } catch (e: any) { console.error(e); }
  finally { loading.value = false; }
}
function onPageChange(p: any) {
  page.value = p.current;
  pageSize.value = p.pageSize;
}
function editProject(p: any) { editing.value = p; form.code = p.code; form.name = p.name; form.type = p.type || ""; form.region = p.region || ""; form.entry_date = p.entry_date || ""; form.product_series = p.product_series || ""; showForm.value = true; }
async function save() {
  saving.value = true;
  try {
    const payload = { name: form.name, type: form.type || null, region: form.region || null, entry_date: form.entry_date || null, product_series: form.product_series || null };
    if (editing.value) await http.patch(`/config/projects/${editing.value.id}`, payload);
    else await http.post("/config/projects", { ...form, ...payload });
    showForm.value = false; editing.value = null; form.code = ""; form.name = ""; form.type = ""; form.region = ""; form.entry_date = ""; form.product_series = "";
    await load();
  } catch (e: any) { alert(e.message); }
  finally { saving.value = false; }
}
onMounted(load);
</script>
<style scoped>
.page .header { margin-bottom: 20px; } .header h1 { font-size: var(--fs-h1); font-weight: 700; } .meta { font-size: 12px; color: var(--muted); }
.card { background: var(--card); border-radius: var(--radius); box-shadow: var(--shadow); overflow: auto; }
.card-hd { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; border-bottom: 1px solid var(--border); }
.card-hd h3 { font-size: 15px; font-weight: 700; }
table { width: 100%; border-collapse: collapse; } th, td { padding: 10px 12px; text-align: left; font-size: 13px; border-bottom: 1px solid var(--border); }
th { background: #f8fafc; font-weight: 600; font-size: 11px; color: var(--muted); } .code { font-family: monospace; font-size: 12px; color: var(--muted); }
.tag { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; }
.tag-green { background: #ecfdf5; color: var(--green); } .tag-red { background: #fef2f2; color: var(--red); } .tag-amber { background: #fffbeb; color: #b45309; }
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: #fff; border-radius: 12px; width: 480px; box-shadow: 0 8px 30px rgba(0,0,0,0.15); }
.modal-hd { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; border-bottom: 1px solid var(--border); }
.modal-hd h3 { font-size: 16px; font-weight: 700; } .btn-close { background: none; border: none; font-size: 18px; cursor: pointer; color: var(--muted); }
.modal-body { padding: 20px; } .form-group { margin-bottom: 12px; } .form-group label { display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px; }
.form-group input, .form-group select { width: 100%; padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; }
.form-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.btn { padding: 8px 16px; border-radius: 6px; border: none; cursor: pointer; font-size: 13px; font-weight: 600; }
.btn-pri { background: var(--brand); color: #fff; } .btn-pri:disabled { opacity: 0.6; }
.btn-out { background: #fff; color: #4b5563; border: 1px solid var(--border); } .btn-sm { padding: 4px 10px; font-size: 11px; }
.pagination-bar { display: flex; justify-content: center; padding: 16px 0 0; }
</style>