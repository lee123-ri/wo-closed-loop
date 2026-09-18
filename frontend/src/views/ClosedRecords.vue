<template>
  <div class="closed-records">
    <div class="page-header">
      <div><h1>闭环记录</h1><p class="meta">已闭环工单归档 · 可追溯</p></div>
      <t-button theme="default" variant="outline" @click="exportCSV">导出当前页 CSV</t-button>
    </div>

    <t-card>
      <div class="filters">
        <t-select v-model="filters.region" placeholder="区域" clearable @change="applyFilters" style="width:120px">
          <t-option v-for="r in regions" :key="r" :value="r" :label="r" />
        </t-select>
        <t-select v-model="filters.project_id" placeholder="项目" clearable filterable @change="applyFilters" style="width:180px">
          <t-option v-for="p in projectOptions" :key="p.id" :value="p.id" :label="p.name" />
        </t-select>
        <t-select v-model="filters.source_code" placeholder="工单类型" clearable @change="applyFilters" style="width:130px">
          <t-option v-for="s in sources" :key="s.code" :value="s.code" :label="s.name" />
        </t-select>
      </div>

      <t-table
        :data="list.items"
        :columns="columns"
        row-key="id"
        :loading="loading"
        hover
        resizable
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
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { listClosedOrders, type WorkOrderList } from "@/api/workorders";
import { getWoTypes, type ConfigItem } from "@/api/config";
import { sourceLabel, sourceTagClass } from "@/utils/wo-display";
import { toast } from "@/utils/feedback";
import { downloadCsv } from "@/utils/csv";
import dayjs from "dayjs";

defineOptions({ name: "ClosedRecords" });

const router = useRouter();
const loading = ref(false);
let reloadSeq = 0; // 请求序号：连续切换筛选时丢弃过期响应
const list = ref<WorkOrderList>({ items: [], total: 0, page: 1, page_size: 20 });
const sources = ref<ConfigItem[]>([]);
const page = ref(1);
const pageSize = ref(20);
const filters = reactive<any>({ project_id: undefined, source_code: undefined, region: undefined });
const regions = ["华北", "华中", "华东", "华南", "西北", "西南", "东北"];

// 项目下拉只列当前归档列表里真实出现过的项目（后端已按列表范围去重 + 按区域收窄）
const projectOptions = computed(() => list.value.project_options || []);
const pagination = reactive({ current: 1, pageSize: 20, total: 0, showJumper: true });

const columns = [
  { colKey: "code", title: "编号", width: 130 },
  { colKey: "project_name", title: "项目", width: 160, ellipsis: true },
  { colKey: "title", title: "标题", width: 240, ellipsis: true },
  { colKey: "reason", title: "触发原因", width: 200, ellipsis: true },
  { colKey: "action", title: "行动要求", width: 200, ellipsis: true },
  { colKey: "person_name", title: "责任人", width: 90 },
  { colKey: "created_date", title: "创建", width: 110 },
  { colKey: "completed_date", title: "闭环", width: 110 },
  { colKey: "duration_days", title: "耗时", width: 90 },
  { colKey: "is_overdue", title: "逾期", width: 120 },
  { colKey: "source_code", title: "工单类型", width: 92 },
];

async function reload() {
  const seq = ++reloadSeq;
  loading.value = true;
  try {
    const params: any = { page: page.value, page_size: pageSize.value, scope: "mine" };
    if (filters.project_id) params.project_id = filters.project_id;
    if (filters.source_code) params.source_code = filters.source_code;
    if (filters.region) params.region = filters.region;
    const res = await listClosedOrders(params);
    if (seq !== reloadSeq) return; // 丢弃过期响应
    list.value = res;
    // 下拉来源已改为「列表内项目」：切换区域后已选项目若不在新范围内，清掉并重拉一次
    if (filters.project_id && !(res.project_options || []).some((p: any) => p.id === filters.project_id)) {
      filters.project_id = undefined;
      page.value = 1;
      return reload();
    }
    // 筛选后当前页可能越界 → 回到第1页重拉
    if (res.items.length === 0 && res.total > 0 && page.value > 1) {
      page.value = 1;
      return reload();
    }
    pagination.total = res.total;
    pagination.current = page.value;
  } catch (e: any) {
    if (seq === reloadSeq) toast.error("闭环记录加载失败：" + (e.message || "未知错误"));
  } finally {
    if (seq === reloadSeq) loading.value = false;
  }
}

/** 筛选条件变化：回到第1页再查（否则带旧页码查询会返回空页，表现为"筛不出东西"） */
function applyFilters() {
  page.value = 1;
  reload();
}
function onPageChange(p: any) { page.value = p.current; pageSize.value = p.pageSize; reload(); }
function goDetail({ row }: any) { router.push(`/work-orders/${row.id}`); }

function exportCSV() {
  if (!list.value.items.length) { toast.warning("当前页没有可导出的工单"); return; }
  const head = ["编号", "项目", "标题", "触发原因", "行动要求", "责任人", "创建", "闭环", "耗时(天)", "逾期", "工单类型"];
  const data = list.value.items.map((w) => [w.code, w.project_name, w.title, w.reason, w.action,
    w.person_name, w.created_date, w.completed_date, w.duration_days,
    w.is_overdue ? `是·超${w.overdue_days}天` : "否", sourceLabel(w.source_code)]);
  downloadCsv([head, ...data], `闭环记录_${dayjs().format("YYYY-MM-DD")}.csv`);
}

onMounted(async () => {
  sources.value = await getWoTypes();
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
