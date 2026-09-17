<template>
  <div class="page">
    <div class="header"><h1>操作日志</h1><div class="meta">谁在什么时候做了什么——项目/用户/工单的关键操作留痕</div></div>
    <div class="card">
      <PageError v-if="loadError" title="日志加载失败" :message="loadError" @action="load" />
      <t-table v-else
        :data="logs"
        :columns="columns"
        row-key="id"
        :loading="loading"
        :pagination="pagination"
        @page-change="onPageChange"
        size="small"
        cell-empty-content="—"
        hover
      >
        <template #created_at="{ row }"><span class="time">{{ row.created_at?.slice(0, 16).replace("T", " ") }}</span></template>
        <template #action="{ row }"><t-tag theme="primary" size="small" variant="light">{{ actionLabel(row.action) }}</t-tag></template>
        <template #target="{ row }">{{ targetLabel(row.target) }} #{{ row.target_id }}</template>
        <template #detail="{ row }"><span class="detail">{{ detailText(row.detail) }}</span></template>
        <template #operator="{ row }">{{ row.operator || "—" }}</template>
      </t-table>
    </div>
  </div>
</template>
<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import http from "@/api/http";
import PageError from "@/components/PageError.vue";

const logs = ref<any[]>([]);
const loading = ref(false);
const loadError = ref("");
const pagination = reactive({ current: 1, pageSize: 20, total: 0, showJumper: true, showPageSize: true, pageSizeOptions: [20, 50, 100] });
const ACTION_LABEL: Record<string, string> = {
  create: "新增", update: "编辑", disable: "停用", update_role: "改角色",
  toggle_active: "启禁变更", transition: "状态流转",
};
const TARGET_LABEL: Record<string, string> = { project: "项目", user: "用户", work_order: "工单" };
function actionLabel(a: string) { return ACTION_LABEL[a] || a; }
function targetLabel(t: string) { return TARGET_LABEL[t] || t; }
function detailText(d: any) {
  if (!d) return "—";
  try {
    const o = JSON.parse(d);
    if (o && typeof o === "object") {
      return Object.entries(o).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v, null, 0) : v}`).join("，");
    }
    return String(d);
  } catch { return String(d); }
}
const columns: any[] = [
  { colKey: "created_at", title: "时间", width: 150 },
  { colKey: "action", title: "操作", width: 90 },
  { colKey: "target", title: "对象", width: 110 },
  { colKey: "detail", title: "详情" },
  { colKey: "operator", title: "操作人", width: 90 },
];

async function load() {
  loading.value = true;
  loadError.value = "";
  try {
    const r: any = await http.get(`/config/audit-logs?page=${pagination.current}&page_size=${pagination.pageSize}`);
    logs.value = r.items || [];
    pagination.total = r.total || 0;
  } catch (e: any) { loadError.value = e.message || "请稍后重试"; }
  finally { loading.value = false; }
}
function onPageChange(p: any) { pagination.current = p.current; pagination.pageSize = p.pageSize; load(); }

onMounted(load);
</script>
<style scoped>
.page .header { margin-bottom: 20px; } .header h1 { font-size: var(--fs-h1); font-weight: 700; } .meta { font-size: 12px; color: var(--muted); }
.card { background: var(--card); border-radius: var(--radius); box-shadow: var(--shadow); }
.time { font-family: monospace; font-size: 12px; color: var(--muted); }
.detail { font-size: 12px; color: var(--muted); }
</style>
