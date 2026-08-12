<template>
  <div class="wo-list">
    <div class="page-header">
      <div>
        <h1>工单列表</h1>
        <p class="meta">全部工单 · 筛选查询</p>
      </div>
      <t-space>
        <t-button theme="default" variant="outline" @click="exportCSV">导出 CSV</t-button>
        <t-button theme="primary" @click="router.push('/create')">＋ 新建工单</t-button>
      </t-space>
    </div>

    <t-card>
      <!-- 筛选 -->
      <div class="filters">
        <t-input v-model="filters.search" placeholder="搜索工单标题..." clearable @change="reload" style="width:200px" />
        <t-select v-model="filters.project_id" placeholder="项目" clearable @change="reload" style="width:160px">
          <t-option v-for="p in projects" :key="p.id" :value="p.id" :label="p.name" />
        </t-select>
        <t-select v-model="filters.source_code" placeholder="来源" clearable @change="reload" style="width:120px">
          <t-option v-for="s in sources" :key="s.code" :value="s.code" :label="s.name" />
        </t-select>
        <t-select v-model="filters.status" placeholder="状态" clearable @change="reload" style="width:120px">
          <t-option v-for="s in statuses" :key="s.code" :value="s.code" :label="s.name" />
        </t-select>
        <t-select v-model="filters.priority" placeholder="优先级" clearable @change="reload" style="width:120px">
          <t-option value="P1" label="P1 紧急" />
          <t-option value="P2" label="P2 普通" />
          <t-option value="P3" label="P3 低优先" />
        </t-select>
        <t-input v-model="filters.person_name" placeholder="责任人搜索" @change="reload" style="width:160px" clearable />
        <t-button theme="default" variant="outline" @click="resetFilters">重置</t-button>
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
        <template #code="{ row }">
          <t-link theme="primary" hover="color">{{ row.code }}</t-link>
        </template>
        <template #source_code="{ row }">
          <span class="src-tag" :class="sourceTagClass(row.source_code)">{{ sourceLabel(row.source_code) }}</span>
        </template>
        <template #priority="{ row }">
          <t-tag :theme="priorityTheme(row.priority)" size="small">{{ priorityLabel(row.priority) }}</t-tag>
        </template>
        <template #status="{ row }">
          <t-tag :theme="statusTheme(row.status)" size="small">{{ statusLabel(row.status) }}</t-tag>
        </template>
        <template #deadline="{ row }">
          <span :style="{ color: row.status === 'overdue' ? 'var(--red)' : '' }">{{ row.deadline }}</span>
        </template>
        <template #escalation="{ row }">
          <t-tag v-if="row.escalation_level > 0" :theme="row.escalation_level >= 3 ? 'danger' : 'warning'" size="small">
            {{ escLabel[row.escalation_level] }}
          </t-tag>
          <span v-else>—</span>
        </template>
      </t-table>
    </t-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { listWorkOrders, type WorkOrderList } from "@/api/workorders";
import { getProjects, getSources, getStatuses, type ConfigItem } from "@/api/config";
import {
  statusLabel, statusTheme, priorityLabel, priorityTheme,
  sourceLabel, sourceTagClass, escLabel,
} from "@/utils/wo-display";

const route = useRoute();
const router = useRouter();
const loading = ref(false);
const list = ref<WorkOrderList>({ items: [], total: 0, page: 1, page_size: 20 });
const projects = ref<any[]>([]);
const sources = ref<ConfigItem[]>([]);
const statuses = ref<ConfigItem[]>([]);
const page = ref(1);
const pageSize = ref(20);

const filters = reactive<any>({ project_id: undefined, source_code: undefined, status: undefined, priority: undefined, person_name: undefined, search: undefined });

const pagination = reactive({
  current: 1, pageSize: 20, total: 0, showJumper: true, showPageSize: true,
  pageSizeOptions: [10, 20, 50],
});

const columns = [
  { colKey: "code", title: "编号", width: 130 },
  { colKey: "source_code", title: "来源", width: 90 },
  { colKey: "project_name", title: "项目", width: 160, ellipsis: true },
  { colKey: "title", title: "标题", minWidth: 200, ellipsis: true },
  { colKey: "type_name", title: "类型", width: 90 },
  { colKey: "priority", title: "优先级", width: 100 },
  { colKey: "person_name", title: "责任人", width: 90 },
  { colKey: "approver_name", title: "审批人", width: 90 },
  { colKey: "deadline", title: "截止", width: 110 },
  { colKey: "status", title: "状态", width: 90 },
  { colKey: "escalation", title: "告警", width: 90 },
];

async function reload() {
  loading.value = true;
  try {
    const params: any = { page: page.value, page_size: pageSize.value };
    for (const [k, v] of Object.entries(filters)) {
      if (v !== undefined && v !== "" && v !== null) params[k] = v;
    }
    list.value = await listWorkOrders(params);
    pagination.total = list.value.total;
    pagination.current = page.value;
  } catch (e: any) { console.error(e); }
  finally { loading.value = false; }
}

function onPageChange(p: any) {
  page.value = p.current;
  pageSize.value = p.pageSize;
  reload();
}

function resetFilters() {
  Object.keys(filters).forEach((k) => (filters[k] = undefined));
  page.value = 1; reload();
}

function goDetail({ row }: any) { router.push(`/work-orders/${row.id}`); }

function exportCSV() {
  const rows = list.value.items;
  const head = ["编号", "来源", "项目", "标题", "类型", "优先级", "责任人", "审批人", "截止", "状态"];
  const lines = [head.join(",")];
  for (const w of rows) {
    lines.push([w.code, sourceLabel(w.source_code), w.project_name || "", `"${w.title}"`, w.type_name || "", w.priority, w.person_name || "", w.approver_name || "", w.deadline || "", statusLabel(w.status)].join(","));
  }
  const blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `工单列表_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
}

onMounted(async () => {
  const q = route.query;
  filters.status = q.status || undefined;
  filters.source_code = q.source_code || undefined;
  filters.priority = q.priority || undefined;
  const [p, s, st] = await Promise.all([getProjects(), getSources(), getStatuses()]);
  projects.value = p; sources.value = s; statuses.value = st;
  await reload();
});
</script>

<style scoped>
.wo-list .page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.page-header h1 { font-size: var(--fs-h1); font-weight: 700; }
.meta { color: var(--muted); font-size: 12px; margin-top: 4px; }
.filters { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
.src-tag { display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 11px; font-weight: 700; }
.src-plan { background: #dbeafe; color: #1e40af; }
.src-alert { background: #fee2e2; color: #991b1b; }
.src-meeting { background: #fef3c7; color: #92400e; }
.src-manual { background: #e0e7ff; color: #3730a3; }
</style>
