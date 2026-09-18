<template>
  <div class="pool-page">
    <div class="header">
      <div><h1>数据池</h1><div class="meta">CSV 导入 · AI表格同步 · 批量生成工单</div></div>
      <div class="header-actions">
        <button class="btn btn-out" @click="doSync" :disabled="syncing">
          {{ syncing ? '同步中…' : '🔄 从 AI 表格同步' }}
        </button>
        <button class="btn btn-out" @click="openUpload">📤 导入 CSV</button>
        <button class="btn btn-pri" @click="generateAll" :disabled="!pendingCount || generating">
          ⚡ {{ generating ? '生成中…' : `一键生成工单 (${totalPending || pendingCount})` }}
        </button>
      </div>
    </div>

    <!-- 上传弹窗 -->
    <t-dialog v-model:visible="showUpload" header="导入 CSV 到数据池" :footer="false" width="520">
      <div class="form-group">
        <label>数据池类型</label>
        <t-select v-model="uploadType" :options="uploadTypeOptions" />
      </div>
      <div class="upload-area" @dragover.prevent @drop.prevent="onDrop">
        <input type="file" accept=".csv" @change="onFilePick" ref="fileInput" hidden />
        <div v-if="!uploadResult" @click="($refs.fileInput as HTMLInputElement)?.click()" class="upload-prompt">
          📁 点击选择 CSV 文件，或拖拽到此处
          <div class="upload-hint">支持列：标题/项目/责任人/截止日期/描述/指标类型/指标值/阈值/偏离</div>
        </div>
        <div v-else class="upload-result">
          <div class="ok" v-if="uploadResult.imported">✅ 导入 {{ uploadResult.imported }} 条</div>
          <div class="warn" v-if="uploadResult.skipped">跳过 {{ uploadResult.skipped }} 条</div>
          <div class="err" v-if="uploadResult.errors.length"><div v-for="(e,i) in uploadResult.errors" :key="i">{{ e }}</div></div>
          <t-button variant="outline" size="small" @click="uploadResult = null">重新上传</t-button>
        </div>
      </div>
    </t-dialog>

    <!-- 筛选 -->
    <div class="filters">
      <t-select v-model="filterType" :options="filterTypeOptions" @change="resetAndLoad" />
      <t-select v-model="filterStatus" :options="filterStatusOptions" @change="resetAndLoad" />
      <span class="total">共 {{ total }} 条</span>
    </div>

    <!-- 表格 -->
    <div class="card">
      <t-table
        v-if="items.length"
        :data="items"
        :columns="columns"
        row-key="id"
        :selected-row-keys="selectedKeys"
        @select-change="onSelectChange"
        :pagination="pagination"
        @page-change="onPageChange"
        size="small"
        cell-empty-content="—"
        hover
      >
        <template #title="{ row }">
          <div class="title-cell"><div class="title">{{ row.title }}</div><div class="desc" v-if="row.description">{{ row.description?.slice(0, 60) }}</div></div>
        </template>
        <template #pool_type="{ row }">
          <span class="tag" :class="row.pool_type === 'plan' ? 'tag-blue' : 'tag-amber'">{{ row.pool_type === 'plan' ? '计划' : '异常' }}</span>
        </template>
        <template #status="{ row }">
          <span class="tag" :class="statusClass(row.status)">{{ statusLabel(row.status) }}</span>
        </template>
        <template #action="{ row }">
          <div class="actions">
            <span v-if="row.work_order_code" class="wo-link" @click="$router.push(`/work-orders/${row.work_order_id}`)">{{ row.work_order_code }}</span>
            <span v-if="row.backfill_reason" class="backfill-dot" title="已回填">✓</span>
            <t-button v-if="row.status !== 'generated'" size="small" variant="outline" @click="deleteItem(row.id)">删除</t-button>
          </div>
        </template>
      </t-table>
      <div v-else class="empty">暂无数据，请导入 CSV</div>
    </div>

    <!-- 批量操作 -->
    <div v-if="selected.size" class="batch-bar">
      已选 {{ selected.size }} 条
      <button class="btn btn-pri" @click="generateSelected" :disabled="generating">{{ generating ? '生成中…' : '生成工单' }}</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { toast, confirmDialog } from "@/utils/feedback";
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { listPoolItems, uploadPoolCSV, generateFromPool, generateAllFromPool, deletePoolItem, syncAITable, type PoolItem, type PoolImportResult } from "@/api/pool";

defineOptions({ name: "DataPool" });

const router = useRouter();
const items = ref<PoolItem[]>([]);
const total = ref(0);
const totalPending = ref(0);
const filterType = ref("");
const filterStatus = ref("");
const filterTypeOptions = [
  { value: "", label: "全部类型" }, { value: "plan", label: "计划类" },
  { value: "anomaly", label: "异常指标类" },
];
const filterStatusOptions = [
  { value: "", label: "全部状态" }, { value: "pending", label: "待生成" },
  { value: "generated", label: "已生成" }, { value: "skipped", label: "已跳过" },
];
const selected = ref(new Set<number>());
const generating = ref(false);
const syncing = ref(false);
const pagination = reactive({ current: 1, pageSize: 20, total: 0, showJumper: true, showPageSize: true, pageSizeOptions: [10, 20, 50, 100] });
const showUpload = ref(false);
const uploadType = ref("plan");
const uploadResult = ref<PoolImportResult | null>(null);
function openUpload() { uploadResult.value = null; showUpload.value = true; }
const fileInput = ref<HTMLInputElement | null>(null);

const pendingCount = computed(() => items.value.filter((i) => i.status === "pending").length);

function statusLabel(s: string) { return { pending: "待生成", generated: "已生成", skipped: "已跳过" }[s] || s; }
function statusClass(s: string) { return { pending: "tag-blue", generated: "tag-green", skipped: "tag-gray" }[s] || ""; }

const uploadTypeOptions = [{ label: "计划类", value: "plan" }, { label: "异常指标类", value: "anomaly" }];
const columns: any[] = [
  { colKey: "row-select", type: "multiple", width: 44, disabled: ({ row }: any) => row.status !== "pending" },
  { colKey: "title", title: "标题", minWidth: 240 },
  { colKey: "pool_type", title: "类型", width: 70 },
  { colKey: "project_name", title: "场站", width: 100 },
  { colKey: "person_name", title: "责任人", width: 80 },
  { colKey: "deadline", title: "截止日期", width: 100 },
  { colKey: "status", title: "状态", width: 80 },
  { colKey: "action", title: "操作", width: 120 },
];
const selectedKeys = computed(() => Array.from(selected.value));
function onSelectChange(keys: (string | number)[]) {
  const allowed = new Set(items.value.filter((i) => i.status === "pending").map((i) => i.id));
  selected.value = new Set((keys as number[]).filter((id) => allowed.has(id)));
}

async function load() {
  try {
    const res = await listPoolItems({ pool_type: filterType.value || undefined, status: filterStatus.value || undefined, page: pagination.current, page_size: pagination.pageSize });
    items.value = res.items; total.value = res.total; pagination.total = res.total;
  } catch (e: any) {
    toast.error("数据池加载失败：" + (e.message || "未知错误"));
    return;
  }
  // 获取待生成总数
  try {
    const p = await listPoolItems({ status: "pending", page_size: 1 });
    totalPending.value = p.total;
  } catch { totalPending.value = 0; }
}

function resetAndLoad() { pagination.current = 1; load(); }
function onPageChange(p: any) { pagination.current = p.current; pagination.pageSize = p.pageSize; load(); }

function onFilePick(e: Event) { const f = (e.target as HTMLInputElement).files?.[0]; if (f) doUpload(f); }
function onDrop(e: DragEvent) { e.preventDefault(); const f = e.dataTransfer?.files?.[0]; if (f) doUpload(f); }
async function doUpload(file: File) {
  try { uploadResult.value = await uploadPoolCSV(uploadType.value, file); await load(); }
  catch (e: any) { toast.error("上传失败：" + e.message); }
}
async function generateSelected() {
  generating.value = true;
  try { const res = await generateFromPool(Array.from(selected.value)); if (res.errors.length) toast.warning("部分失败：" + res.errors.join("；")); selected.value = new Set(); await load(); }
  catch (e: any) { toast.error("生成失败：" + e.message); }
  finally { generating.value = false; }
}
async function generateAll() {
  generating.value = true;
  try { const res = await generateAllFromPool(filterType.value || undefined); if (res.errors.length) toast.warning("部分失败：" + res.errors.join("；")); await load(); }
  catch (e: any) { toast.error("生成失败：" + e.message); }
  finally { generating.value = false; }
}
async function deleteItem(id: number) { if (!(await confirmDialog("确认删除？"))) return; try { await deletePoolItem(id); await load(); } catch (e: any) { toast.error("删除失败：" + e.message); } }

async function doSync() {
  syncing.value = true;
  try {
    const res = await syncAITable("", "");
    toast.success(`同步完成：导入 ${res.imported} 条，跳过 ${res.skipped} 条`);
    await load();
  } catch (e: any) { toast.error("同步失败：" + e.message); }
  finally { syncing.value = false; }
}

onMounted(load);
</script>

<style scoped>
.pool-page .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; gap: 16px; flex-wrap: wrap; }
.header h1 { font-size: var(--fs-h1); font-weight: 700; } .meta { font-size: 12px; color: var(--muted); } .header-actions { display: flex; gap: 8px; }
.filters { display: flex; gap: 10px; align-items: center; margin-bottom: 16px; }
.filters :deep(.t-select) { width: 160px; } .total { font-size: 12px; color: var(--muted); margin-left: auto; }
.card { background: var(--card); border-radius: var(--radius); box-shadow: var(--shadow); }
.title-cell .title { font-weight: 600; } .title-cell .desc { font-size: 11px; color: var(--muted); margin-top: 2px; }
.actions { display: flex; gap: 6px; align-items: center; } .wo-link { cursor: pointer; color: var(--brand); font-size: 11px; font-weight: 600; } .wo-link:hover { text-decoration: underline; }
.backfill-dot { color: var(--green); font-weight: 700; font-size: 14px; } .empty { text-align: center; padding: 40px; color: var(--muted); }
.batch-bar { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); background: #1e293b; color: #fff; padding: 10px 20px; border-radius: 10px; display: flex; gap: 12px; align-items: center; font-size: 13px; box-shadow: 0 4px 12px rgba(0,0,0,0.2); z-index: 10; }
.form-group { margin-bottom: 14px; } .form-group label { display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px; }
.form-group select { width: 100%; padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px; }
.upload-area { min-height: 120px; border: 2px dashed #d1d5db; border-radius: 10px; display: flex; align-items: center; justify-content: center; cursor: pointer; }
.upload-area:hover { border-color: var(--brand); background: #f8fafc; } .upload-prompt { text-align: center; color: var(--muted); font-size: 14px; }
.upload-hint { font-size: 11px; margin-top: 8px; color: #9ca3af; } .upload-result { text-align: center; padding: 12px; }
.ok { color: var(--green); font-weight: 600; } .warn { color: var(--amber); font-size: 12px; } .err { color: var(--red); font-size: 11px; }
.tag { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; white-space: nowrap; }
.tag-blue { background: #eff6ff; color: var(--brand); } .tag-green { background: #ecfdf5; color: var(--green); } .tag-amber { background: #fffbeb; color: var(--amber); } .tag-gray { background: #f3f4f6; color: #6b7280; }
</style>
