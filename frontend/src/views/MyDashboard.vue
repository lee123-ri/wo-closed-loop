<template>
  <div class="my-page">
    <div class="header">
      <div><h1>{{ pageTitle }}</h1><div class="meta">{{ scopeLabel }}</div></div>
    </div>

    <!-- 统计卡片（点击筛状态） -->
    <PageError v-if="statsError" title="统计加载失败" :message="statsError" @action="load" />
    <div class="stats-row" v-else-if="stats">
      <button type="button" class="stat-card" :class="{ on: filterStatus === '' }" :aria-pressed="filterStatus === ''" @click="setFilter('')">
        <div class="num">{{ stats.total }}</div>
        <div class="lbl">全部工单</div>
      </button>
      <button type="button" class="stat-card warn" :class="{ on: filterStatus === 'overdue' }" :aria-pressed="filterStatus === 'overdue'" @click="setFilter('overdue')">
        <div class="num">{{ stats.overdue }}</div>
        <div class="lbl">已逾期</div>
      </button>
      <button type="button" class="stat-card primary" :class="{ on: filterStatus === 'executing' }" :aria-pressed="filterStatus === 'executing'" @click="setFilter('executing')">
        <div class="num">{{ stats.executing }}</div>
        <div class="lbl">执行中</div>
      </button>
      <button type="button" class="stat-card amber" :class="{ on: filterStatus === 'verifying' }" :aria-pressed="filterStatus === 'verifying'" @click="setFilter('verifying')">
        <div class="num">{{ stats.verifying }}</div>
        <div class="lbl">待验收</div>
      </button>
      <button type="button" class="stat-card blue" :class="{ on: filterStatus === 'pending' }" :aria-pressed="filterStatus === 'pending'" @click="setFilter('pending')">
        <div class="num">{{ stats.pending }}</div>
        <div class="lbl">待处理</div>
      </button>
      <button type="button" class="stat-card" :class="{ on: filterStatus === 'need_backfill' }" :aria-pressed="filterStatus === 'need_backfill'" @click="setFilter('need_backfill')">
        <div class="num">{{ stats.need_backfill }}</div>
        <div class="lbl">待回填</div>
      </button>
    </div>

    <!-- 宽表工作台（就地流转） -->
    <div class="card">
      <div class="card-hd">
        <h3>工单列表</h3>
        <span class="count">共 {{ woList.total }} 条{{ filterStatus ? '（已筛选状态）' : '' }}</span>
      </div>
      <WorkbenchTable
        :items="woList.items"
        :loading="loading"
        :total="woList.total"
        :page="page"
        :page-size="pageSize"
        :users="users"
        @row-click="goDetail"
        @reload="load"
        @page-change="onPageChange"
      />
    </div>

    <!-- 日历（本月） -->
    <div class="card">
      <div class="card-hd">
        <h3>本月日历 · {{ currentMonthLabel }}</h3>
        <div class="cal-nav">
          <t-button size="small" variant="outline" @click="changeMonth(-1)">‹</t-button>
          <t-button size="small" variant="outline" @click="changeMonth(1)">›</t-button>
        </div>
      </div>
      <PageError v-if="calendarError" title="日历加载失败" :message="calendarError" @action="loadCalendar" />
      <div v-else class="mini-cal">
        <div class="cal-header">
          <div v-for="d in dayNames" :key="d" class="cal-day-name">{{ d }}</div>
        </div>
        <div class="cal-grid">
          <div v-for="(day, i) in calendarDays" :key="i" class="cal-day" :class="dayClass(day)">
            <div class="cal-date">{{ day.date }}</div>
            <div v-for="wo in day.items" :key="wo.id" class="cal-item" :class="'cal-' + wo.status" @click="goDetail(wo)">
              <span class="cal-dot"></span>
              <span class="cal-text">{{ wo.code.slice(-4) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { toast } from "@/utils/feedback";
import { listWorkOrders, type WorkOrderList } from "@/api/workorders";
import { getMyDashboard, getCalendar } from "@/api/pool";
import { getUsersAll } from "@/api/config";
import { useUserStore } from "@/stores/user";
import WorkbenchTable from "@/components/WorkbenchTable.vue";
import PageError from "@/components/PageError.vue";
import dayjs from "dayjs";

const router = useRouter();
const userStore = useUserStore();
const users = ref<any[]>([]);
const stats = ref<any>(null);
const statsError = ref("");
const calendarError = ref("");
const scope = ref("self"); // all | region | self
const filterStatus = ref("");
const woList = ref<WorkOrderList>({ items: [], total: 0, page: 1, page_size: 20 });
const loading = ref(false);
const page = ref(1);
const pageSize = ref(20);
const calendarYear = ref(new Date().getFullYear());
const calendarMonth = ref(new Date().getMonth() + 1);
const currentMonthLabel = computed(() => `${calendarYear.value}年${calendarMonth.value}月`);
const dayNames = ["一", "二", "三", "四", "五", "六", "日"];
const calendarDays = ref<any[]>([]);

const meName = computed(() => userStore.user?.name || "我");
const pageTitle = computed(() =>
  scope.value === "all" ? "全部工单" : scope.value === "region" ? "区域工单" : "我的工单"
);
const scopeLabel = computed(() => {
  if (scope.value === "all") return `${meName.value} · 管理员可看全部`;
  if (scope.value === "region") return `${meName.value} · 区域PMO看本区域`;
  return `${meName.value} · 只看与我相关（责任人/审批人）`;
});

async function load() {
  statsError.value = "";
  try {
    const res = await getMyDashboard();
    stats.value = res.stats;
    scope.value = res.scope || "self";
    await loadCalendar();
  } catch (e: any) {
    stats.value = null;
    statsError.value = e.message || "请稍后重试";
  }
  await loadList();
}
async function loadList() {
  loading.value = true;
  try {
    const params: any = { page: page.value, page_size: pageSize.value, scope: "mine" };
    if (["pending", "executing", "need_backfill"].includes(filterStatus.value)) {
      params.bucket = filterStatus.value;
    } else if (filterStatus.value) {
      params.status = filterStatus.value;
    } else {
      params.include_closed = true;
    }
    const res = await listWorkOrders(params);
    woList.value = res;
    if (res.items.length === 0 && res.total > 0 && page.value > 1) {
      page.value = 1;
      return loadList();
    }
  } catch (e: any) {
    toast.error("工单加载失败：" + (e.message || "未知错误"));
  } finally {
    loading.value = false;
  }
}
function setFilter(s: string) {
  filterStatus.value = s;
  page.value = 1;
  loadList();
}
function onPageChange(p: any) {
  page.value = p.current;
  pageSize.value = p.pageSize;
  loadList();
}
function goDetail(row: any) {
  if (row && row.id) router.push(`/work-orders/${row.id}`);
}

async function loadCalendar() {
  calendarError.value = "";
  try {
    const res = await getCalendar(calendarYear.value, calendarMonth.value, true);
    const days: any[] = [];
    const first = new Date(calendarYear.value, calendarMonth.value - 1, 1);
    const last = new Date(calendarYear.value, calendarMonth.value, 0);
    const startDow = first.getDay() || 7;
    for (let i = 1; i < startDow; i++) days.push({ date: "", items: [], empty: true });
    for (let d = 1; d <= last.getDate(); d++) {
      const dateStr = `${calendarYear.value}-${String(calendarMonth.value).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      const dayItems = res.items.filter((i: any) => i.deadline === dateStr);
      days.push({ date: d, items: dayItems, today: dateStr === dayjs().format("YYYY-MM-DD"), empty: false });
    }
    calendarDays.value = days;
  } catch (e: any) {
    calendarError.value = e.message || "请稍后重试";
  }
}
function dayClass(day: any) {
  return {
    "cal-today": day.today,
    "cal-empty": day.empty,
    "cal-has-items": day.items.length > 0,
  };
}
function changeMonth(delta: number) {
  calendarMonth.value += delta;
  if (calendarMonth.value > 12) { calendarMonth.value = 1; calendarYear.value++; }
  if (calendarMonth.value < 1) { calendarMonth.value = 12; calendarYear.value--; }
  loadCalendar();
}

onMounted(async () => {
  try { users.value = await getUsersAll(); }
  catch (e: any) { toast.warning("人员列表加载失败：" + (e.message || "未知错误")); }
  await load();
});
</script>

<style scoped>
.my-page .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; gap: 16px; flex-wrap: wrap; }
.header h1 { font-size: var(--fs-h1); font-weight: 700; }
.meta { font-size: 12px; color: var(--muted); }

.stats-row { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin-bottom: 16px; }
.stat-card { background: var(--card); border-radius: var(--radius); padding: 16px; width: 100%; text-align: center; box-shadow: var(--shadow); cursor: pointer; border: 1px solid transparent; font: inherit; color: inherit; transition: transform .15s, box-shadow .15s; }
.stat-card:hover { transform: translateY(-1px); }
.stat-card.on { border-color: var(--brand); box-shadow: 0 0 0 2px var(--brand-light); }
.stat-card:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; }
.stat-card .num { font-size: 28px; font-weight: 700; }
.stat-card .lbl { font-size: 11px; color: var(--muted); margin-top: 2px; }
.stat-card.warn .num { color: var(--red); }
.stat-card.primary .num { color: var(--brand); }
.stat-card.amber .num { color: var(--amber); }
.stat-card.blue .num { color: #2563eb; }
@media (max-width: 1200px) { .stats-row { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 800px) { .stats-row { grid-template-columns: repeat(2, minmax(0, 1fr)); } }

.card { background: var(--card); border-radius: var(--radius); box-shadow: var(--shadow); margin-bottom: 16px; overflow: auto; }
.card-hd { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; border-bottom: 1px solid var(--border); }
.card-hd h3 { font-size: 15px; font-weight: 700; }
.count { font-size: 12px; color: var(--muted); }

.cal-nav { display: flex; gap: 4px; }
.mini-cal { padding: 12px; }
.cal-header { display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px; margin-bottom: 4px; }
.cal-day-name { text-align: center; font-size: 11px; font-weight: 600; color: var(--muted); padding: 4px 0; }
.cal-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px; }
.cal-day { min-height: 60px; padding: 4px; border-radius: 4px; background: #fafafa; }
.cal-empty { background: transparent; }
.cal-today { background: #eff6ff; border: 1px solid var(--brand); }
.cal-has-items { background: #f8fafc; }
.cal-date { font-size: 11px; font-weight: 600; color: var(--muted); margin-bottom: 2px; }
.cal-today .cal-date { color: var(--brand); }
.cal-item { font-size: 10px; display: flex; align-items: center; gap: 3px; margin-bottom: 1px; cursor: pointer; }
.cal-item:hover { background: #e5e7eb; border-radius: 2px; }
.cal-dot { width: 4px; height: 4px; border-radius: 50%; flex-shrink: 0; }
.cal-overdue .cal-dot { background: var(--red); }
.cal-executing .cal-dot { background: var(--brand); }
.cal-verifying .cal-dot { background: var(--amber); }
.cal-pending .cal-dot { background: #9ca3af; }
.cal-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
