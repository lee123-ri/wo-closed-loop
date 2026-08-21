<template>
  <div class="pool-page">
    <div class="header">
      <div><h1>数据池</h1><div class="meta">CSV 导入 · AI表格同步 · 批量生成工单</div></div>
      <div class="header-actions">
        <button class="btn btn-out" @click="doSync" :disabled="syncing">
          {{ syncing ? '同步中…' : '🔄 从 AI 表格同步' }}
        </button>
        <button class="btn btn-out" @click="doFullSync" :disabled="fullSyncing">
          {{ fullSyncing ? '同步中…' : '🚀 一键全链路同步' }}
        </button>
        <button class="btn btn-out" @click="showUpload = true">📤 导入 CSV</button>
        <button class="btn btn-pri" @click="generateAll" :disabled="!pendingCount || generating">
          ⚡ {{ generating ? '生成中…' : `一键生成工单 (${totalPending || pendingCount})` }}
        </button>
      </div>
    </div>

    <!-- 上传弹窗 -->
    <div v-if="showUpload" class="modal-overlay" @click.self="showUpload = false">
      <div class="modal">
        <div class="modal-hd"><h3>导入 CSV 到数据池</h3><button class="btn-close" @click="showUpload = false">✕</button></div>
        <div class="modal-body">
          <div class="form-group">
            <label>数据池类型</label>
            <select v-model="uploadType">
              <option value="plan">计划类</option>
              <option value="anomaly">异常指标类</option>
            </select>
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
              <button class="btn btn-out btn-sm" @click="uploadResult = null">重新上传</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 筛选 -->
    <div class="filters">
      <select v-model="filterType" @change="load">
        <option value="">全部类型</option><option value="plan">计划类</option><option value="anomaly">异常指标类</option>
      </select>
      <select v-model="filterStatus" @change="load">
        <option value="">全部状态</option><option value="pending">待生成</option><option value="generated">已生成</option><option value="skipped">已跳过</option>
      </select>
      <span class="total">共 {{ total }} 条</span>
    </div>

    <!-- 表格 -->
    <div class="card">
      <table v-if="items.length">
        <thead><tr><th style="width:40px"><input type="checkbox" @change="toggleAll" :checked="allSelected" /></th><th>标题</th><th style="width:70px">类型</th><th style="width:90px">场站</th><th style="width:70px">责任人</th><th style="width:90px">截止日期</th><th style="width:70px">状态</th><th style="width:80px">操作</th></tr></thead>
        <tbody>
          <tr v-for="item in items" :key="item.id" :class="{ selected: selected.has(item.id) }">
            <td><input type="checkbox" :checked="selected.has(item.id)" @change="toggleOne(item.id)" :disabled="item.status !== 'pending'" /></td>
            <td class="title-cell"><div class="title">{{ item.title }}</div><div class="desc" v-if="item.description">{{ item.description?.slice(0, 60) }}</div></td>
            <td><span class="tag" :class="item.pool_type === 'plan' ? 'tag-blue' : 'tag-amber'">{{ item.pool_type === 'plan' ? '计划' : '异常' }}</span></td>
            <td>{{ item.project_name || '—' }}</td><td>{{ item.person_name || '—' }}</td><td>{{ item.deadline || '—' }}</td>
            <td><span class="tag" :class="statusClass(item.status)">{{ statusLabel(item.status) }}</span></td>
            <td class="actions">
              <span v-if="item.work_order_code" class="wo-link" @click="$router.push(`/work-orders/${item.work_order_id}`)">{{ item.work_order_code }}</span>
              <span v-if="item.backfill_reason" class="backfill-dot" title="已回填">✓</span>
              <button class="btn btn-sm btn-out" @click="deleteItem(item.id)" v-if="item.status !== 'generated'">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
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
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { listPoolItems, uploadPoolCSV, generateFromPool, generateAllFromPool, deletePoolItem, syncAITable, syncFull, type PoolItem, type PoolImportResult } from "@/api/pool";

const router = useRouter();
const items = ref<PoolItem[]>([]);
const total = ref(0);
const totalPending = ref(0);
const filterType = ref("");
const filterStatus = ref("");
const selected = ref(new Set<number>());
const generating = ref(false);
const syncing = ref(false);
const fullSyncing = ref(false);
const showUpload = ref(false);
const uploadType = ref("plan");
const uploadResult = ref<PoolImportResult | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);

const pendingCount = computed(() => items.value.filter((i) => i.status === "pending").length);
const allSelected = computed(() => items.value.filter((i) => i.status === "pending").every((i) => selected.value.has(i.id)));

function statusLabel(s: string) { return { pending: "待生成", generated: "已生成", skipped: "已跳过" }[s] || s; }
function statusClass(s: string) { return { pending: "tag-blue", generated: "tag-green", skipped: "tag-gray" }[s] || ""; }

async function load() {
  const res = await listPoolItems({ pool_type: filterType.value || undefined, status: filterStatus.value || undefined, page_size: 50 });
  items.value = res.items; total.value = res.total;
  // 获取待生成总数
  try {
    const p = await listPoolItems({ status: "pending", page_size: 1 });
    totalPending.value = p.total;
  } catch { totalPending.value = 0; }
}
function toggleAll() { if (allSelected.value) selected.value = new Set(); else items.value.filter((i) => i.status === "pending").forEach((i) => selected.value.add(i.id)); }
function toggleOne(id: number) { if (selected.value.has(id)) selected.value.delete(id); else selected.value.add(id); }

function onFilePick(e: Event) { const f = (e.target as HTMLInputElement).files?.[0]; if (f) doUpload(f); }
function onDrop(e: DragEvent) { e.preventDefault(); const f = e.dataTransfer?.files?.[0]; if (f) doUpload(f); }
async function doUpload(file: File) {
  try { uploadResult.value = await uploadPoolCSV(uploadType.value, file); await load(); }
  catch (e: any) { alert("上传失败：" + e.message); }
}
async function generateSelected() {
  generating.value = true;
  try { const res = await generateFromPool(Array.from(selected.value)); if (res.errors.length) alert("部分失败：" + res.errors.join("；")); selected.value = new Set(); await load(); }
  catch (e: any) { alert("生成失败：" + e.message); }
  finally { generating.value = false; }
}
async function generateAll() {
  generating.value = true;
  try { const res = await generateAllFromPool(filterType.value || undefined); if (res.errors.length) alert("部分失败：" + res.errors.join("；")); await load(); }
  catch (e: any) { alert("生成失败：" + e.message); }
  finally { generating.value = false; }
}
async function deleteItem(id: number) { if (!confirm("确认删除？")) return; try { await deletePoolItem(id); await load(); } catch (e: any) { alert("删除失败：" + e.message); } }

async function doSync() {
  syncing.value = true;
  try {
    const res = await syncAITable("", "");
    alert(`同步完成：导入 ${res.imported} 条，跳过 ${res.skipped} 条`);
    await load();
  } catch (e: any) { alert("同步失败：" + e.message); }
  finally { syncing.value = false; }
}

async function doFullSync() {
  if (!confirm("一键全链路同步：AITable→数据池→生成工单，并搜索钉盘「工单版」xlsx 导入。可能需要几分钟，确认继续？")) return;
  fullSyncing.value = true;
  try {
    const res = await syncFull();
    const lines = [
      `AITable：异常指标导入 ${res.aitable?.anomaly_synced} 条、非EAM ${res.aitable?.non_eam_synced} 条`,
      `数据池生成工单：${res.pool_generated} 条`,
      `钉盘「工单版」导入：${res.drive_imported} 条（文件 ${res.drive_files} 个）`,
    ];
    if (res.errors?.length) lines.push("⚠️ " + res.errors.join("；"));
    alert("✅ 同步完成\n" + lines.join("\n"));
    await load();
  } catch (e: any) { alert("同步失败：" + e.message); }
  finally { fullSyncing.value = false; }
}

onMounted(load);
</script>

<style scoped>
.pool-page .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; gap: 16px; flex-wrap: wrap; }
.header h1 { font-size: var(--fs-h1); font-weight: 700; } .meta { font-size: 12px; color: var(--muted); } .header-actions { display: flex; gap: 8px; }
.filters { display: flex; gap: 10px; align-items: center; margin-bottom: 16px; }
.filters select { padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 12px; } .total { font-size: 12px; color: var(--muted); margin-left: auto; }
.card { background: var(--card); border-radius: var(--radius); box-shadow: var(--shadow); overflow: auto; }
table { width: 100%; border-collapse: collapse; } th, td { padding: 10px 12px; text-align: left; font-size: 13px; border-bottom: 1px solid var(--border); }
th { background: #f8fafc; font-weight: 600; font-size: 11px; color: var(--muted); } tr.selected { background: #eff6ff; }
.title-cell .title { font-weight: 600; } .title-cell .desc { font-size: 11px; color: var(--muted); margin-top: 2px; }
.actions { display: flex; gap: 6px; align-items: center; } .wo-link { cursor: pointer; color: var(--brand); font-size: 11px; font-weight: 600; } .wo-link:hover { text-decoration: underline; }
.backfill-dot { color: var(--green); font-weight: 700; font-size: 14px; } .empty { text-align: center; padding: 40px; color: var(--muted); }
.batch-bar { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); background: #1e293b; color: #fff; padding: 10px 20px; border-radius: 10px; display: flex; gap: 12px; align-items: center; font-size: 13px; box-shadow: 0 4px 12px rgba(0,0,0,0.2); z-index: 10; }
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: #fff; border-radius: 12px; width: 520px; max-height: 80vh; overflow: auto; box-shadow: 0 8px 30px rgba(0,0,0,0.15); }
.modal-hd { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; border-bottom: 1px solid var(--border); }
.modal-hd h3 { font-size: 16px; font-weight: 700; } .btn-close { background: none; border: none; font-size: 18px; cursor: pointer; color: var(--muted); }
.modal-body { padding: 20px; } .form-group { margin-bottom: 14px; } .form-group label { display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px; }
.form-group select { width: 100%; padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px; }
.upload-area { min-height: 120px; border: 2px dashed #d1d5db; border-radius: 10px; display: flex; align-items: center; justify-content: center; cursor: pointer; }
.upload-area:hover { border-color: var(--brand); background: #f8fafc; } .upload-prompt { text-align: center; color: var(--muted); font-size: 14px; }
.upload-hint { font-size: 11px; margin-top: 8px; color: #9ca3af; } .upload-result { text-align: center; padding: 12px; }
.ok { color: var(--green); font-weight: 600; } .warn { color: var(--amber); font-size: 12px; } .err { color: var(--red); font-size: 11px; }
.tag { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; white-space: nowrap; }
.tag-blue { background: #eff6ff; color: var(--brand); } .tag-green { background: #ecfdf5; color: var(--green); } .tag-amber { background: #fffbeb; color: var(--amber); } .tag-gray { background: #f3f4f6; color: #6b7280; }
.btn { padding: 8px 16px; border-radius: 6px; border: none; cursor: pointer; font-size: 13px; font-weight: 600; }
.btn-pri { background: var(--brand); color: #fff; } .btn-pri:disabled { opacity: 0.6; cursor: not-allowed; } .btn-out { background: #fff; color: #4b5563; border: 1px solid var(--border); } .btn-sm { padding: 4px 10px; font-size: 11px; }
</style>