<template>
  <div class="closed-records">
    <div class="page-header">
      <div><h1>闭环记录</h1><p class="meta">已闭环工单归档 · 可追溯</p></div>
      <t-button theme="default" variant="outline" @click="exportCSV">导出 CSV</t-button>
    </div>

    <t-card>
      <div class="filters">
        <t-select v-model="filters.project_id" placeholder="项目" clearable @change="reload" style="width:160px">
          <t-option v-for="p in projects" :key="p.id" :value="p.id" :label="p.name" />
        </t-select>
        <t-select v-model="filters.source_code" placeholder="来源" clearable @change="reload" style="width:120px">
          <t-option v-for="s in sources" :key="s.code" :value="s.code" :label="s.name" />
        </t-select>
      </div>

      <t-table
        :data="list.items"
        :columns="columns"
        row-key="id"
        :loading="loading"
        hover
        @row-click="goDetail"
        :pagination="pagination"
        @page-change="onPageChange"
        size="small"
        cell-empty-content="—"
      >
        <template #code="{ row }"><t-link theme="primary" hover="color">{{ row.code }}</t-link></template>
        <template #source_code="{ row }">
          <span class="src-tag" :class="sourceTagClass(row.source_code)">{{ sourceLabel(row.source_code) }}</span>
        </template>
        <template #duration_days="{ row }">{{ row.duration_days ?? '—' }} 天</template>
        <template #is_overdue="{ row }">
          <t-tag v-if="row.is_overdue" theme="danger" size="small">是 · 超{{ row.overdue_days }}天</t-tag>
          <t-tag v-else theme="success" size="small">否</t-tag>
        </template>
      </t-table>
    </t-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { listClosedOrders, type WorkOrderList } from "@/api/workorders";
import { getProjects, getSources, type ConfigItem } from "@/api/config";
import { sourceLabel, sourceTagClass } from "@/utils/wo-display";

const router = useRouter();
const loading = ref(false);
const list = ref<WorkOrderList>({ items: [], total: 0, page: 1, page_size: 20 });
const projects = ref<any[]>([]);
const sources = ref<ConfigItem[]>([]);
const page = ref(1);
const pageSize = ref(20);
const filters = reactive<any>({ project_id: undefined, source_code: undefined });
const pagination = reactive({ current: 1, pageSize: 20, total: 0, showJumper: true });

const columns = [
  { colKey: "code", title: "编号", width: 130 },
  { colKey: "source_code", title: "来源", width: 90 },
  { colKey: "project_name", title: "项目", width: 160, ellipsis: true },
  { colKey: "title", title: "标题", minWidth: 200, ellipsis: true },
  { colKey: "person_name", title: "责任人", width: 90 },
  { colKey: "created_date", title: "创建", width: 110 },
  { colKey: "completed_date", title: "闭环", width: 110 },
  { colKey: "duration_days", title: "耗时", width: 90 },
  { colKey: "is_overdue", title: "逾期", width: 120 },
];

async function reload() {
  loading.value = true;
  try {
    const params: any = { page: page.value, page_size: pageSize.value };
    if (filters.project_id) params.project_id = filters.project_id;
    if (filters.source_code) params.source_code = filters.source_code;
    list.value = await listClosedOrders(params);
    pagination.total = list.value.total;
    pagination.current = page.value;
  } catch (e) { console.error(e); }
  finally { loading.value = false; }
}
function onPageChange(p: any) { page.value = p.current; pageSize.value = p.pageSize; reload(); }
function goDetail({ row }: any) { router.push(`/work-orders/${row.id}`); }

function exportCSV() {
  const head = ["编号", "来源", "项目", "标题", "责任人", "创建", "闭环", "耗时(天)", "逾期"];
  const lines = [head.join(",")];
  for (const w of list.value.items) {
    lines.push([w.code, sourceLabel(w.source_code), w.project_name || "", `"${w.title}"`, w.person_name || "", w.created_date, w.completed_date || "", String(w.duration_days ?? ""), w.is_overdue ? `是·超${w.overdue_days}天` : "否"].join(","));
  }
  const blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `闭环记录_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
}

onMounted(async () => {
  const [p, s] = await Promise.all([getProjects(), getSources()]);
  projects.value = p; sources.value = s;
  await reload();
});
</script>

<style scoped>
.closed-records .page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.page-header h1 { font-size: var(--fs-h1); font-weight: 700; }
.meta { color: var(--muted); font-size: 12px; margin-top: 4px; }
.filters { display: flex; gap: 8px; margin-bottom: 16px; }
.src-tag { display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 11px; font-weight: 700; }
.src-plan { background: #dbeafe; color: #1e40af; }
.src-alert { background: #fee2e2; color: #991b1b; }
.src-meeting { background: #fef3c7; color: #92400e; }
.src-manual { background: #e0e7ff; color: #3730a3; }
</style>
