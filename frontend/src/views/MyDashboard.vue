<template>
  <div class="my-page">
    <div class="header page-header">
      <div><h1>{{ pageTitle }}</h1><div class="meta">{{ scopeLabel }}</div></div>
    </div>

    <!-- 角色口径：本人责任 / 本人审批 / 双重角色 / 全部相关 -->
    <div class="role-tabs">
      <span class="role-tabs-label">口径</span>
      <button v-for="o in roleOptions" :key="o.value" type="button" class="role-tab" :class="{ on: role === o.value }" :aria-pressed="role === o.value" @click="setRole(o.value)">
        {{ o.label }}
      </button>
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
      <div v-else-if="calendarHasItems === false" class="cal-empty-banner">
        <div class="cal-empty-icon">📅</div>
        <div class="cal-empty-title">本月没有属于你的工单日程</div>
        <div class="cal-empty-desc">点击上方 ‹ › 切换月份，或去「新建工单」添加计划开始 / 截止日期</div>
      </div>
      <div v-else class="mini-cal">
        <div class="cal-header">
          <div v-for="d in dayNames" :key="d" class="cal-day-name">{{ d }}</div>
        </div>
        <div class="cal-grid">
          <div v-for="(day, i) in calendarDays" :key="i" class="cal-day" :class="dayClass(day)">
            <div class="cal-date">{{ day.date }}</div>
            <div v-for="wo in day.visible" :key="`${wo.id}-${wo.calendar_kind}`" class="cal-item" :class="itemClass(wo)" @click="goDetail(wo)">
              <span class="cal-dot"></span>
              <span class="cal-text">{{ itemKindLabel(wo) }} {{ wo.code.slice(-4) }}</span>
            </div>
            <div v-if="day.hidden > 0" class="cal-item cal-more">＋{{ day.hidden }} 更多</div>
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
const scope = ref("personal");
const role = ref<string>("all");
const roleOptions = [
  { value: "all", label: "全部相关" },
  { value: "responsible", label: "本人责任" },
  { value: "approver", label: "本人审批" },
  { value: "both", label: "双重角色" },
];
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
const calendarHasItems = ref<boolean | null>(null);
const MAX_CAL_ITEMS = 4;

const meName = computed(() => userStore.user?.name || "我");
const pageTitle = computed(() => "我的工单");
const roleLabel = computed(() => roleOptions.find((o) => o.value === role.value)?.label || "");
const scopeLabel = computed(() => `${meName.value} · ${roleLabel.value}（仅本人作为责任人或审批人的工单）`);

async function load() {
  statsError.value = "";
  try {
    const res = await getMyDashboard(role.value);
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
    const params: any = { page: page.value, page_size: pageSize.value, scope: "personal", role: role.value };
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
function setRole(r: string) {
  role.value = r;
  filterStatus.value = "";
  page.value = 1;
  load();
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
    const res = await getCalendar(calendarYear.value, calendarMonth.value, true, role.value);
    const days: any[] = [];
    const first = new Date(calendarYear.value, calendarMonth.value - 1, 1);
    const last = new Date(calendarYear.value, calendarMonth.value, 0);
    const startDow = first.getDay() || 7;
    const todayStr = dayjs().format("YYYY-MM-DD");
    for (let i = 1; i < startDow; i++) days.push({ date: "", visible: [], hidden: 0, empty: true });
    let anyItem = false;
    for (let d = 1; d <= last.getDate(); d++) {
      const dateStr = `${calendarYear.value}-${String(calendarMonth.value).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      const dayItems = res.items.flatMap((i: any) => [
        ...(i.deadline === dateStr ? [{ ...i, calendar_kind: "deadline" }] : []),
        ...(i.planned_start_date === dateStr ? [{ ...i, calendar_kind: "start" }] : []),
      ]);
      if (dayItems.length) anyItem = true;
      days.push({
        date: d,
        visible: dayItems.slice(0, MAX_CAL_ITEMS),
        hidden: Math.max(0, dayItems.length - MAX_CAL_ITEMS),
        today: dateStr === todayStr,
        empty: false,
      });
    }
    calendarDays.value = days;
    calendarHasItems.value = anyItem;
  } catch (e: any) {
    calendarHasItems.value = null;
    calendarError.value = e.message || "请稍后重试";
  }
}
function dayClass(day: any) {
  return {
    "cal-today": day.today,
    "cal-empty": day.empty,
    "cal-has-items": day.visible?.length > 0 || day.hidden > 0,
  };
}
function itemKindLabel(item: any) {
  return item.calendar_kind === "start" ? "开始" : "截止";
}
function itemIsOverdue(item: any) {
  if (item.calendar_kind !== "deadline") return false;
  const d = item.deadline;
  return !!d && d < dayjs().format("YYYY-MM-DD");
}
function itemClass(item: any) {
  return [
    "cal-" + item.status,
    "cal-" + item.calendar_kind,
    { "cal-past": itemIsOverdue(item) },
  ];
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
.my-page .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; gap: 16px; flex-wrap: wrap; }
.header h1 { font-size: var(--fs-h1); font-weight: 700; line-height: 1.35; }
.meta { font-size: 12px; color: var(--muted); }

.stats-row { display: grid; grid-template-columns: repeat(6, 1fr); gap: 0; margin-bottom: 16px; background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); overflow: hidden; }
.stat-card { position: relative; background: transparent; padding: 14px 10px; width: 100%; min-height: 76px; text-align: left; cursor: pointer; border: 0; border-right: 1px solid var(--border); font: inherit; color: inherit; transition: background .15s; }
.stat-card:last-child { border-right: 0; }
.stat-card:hover { background: #f8fafc; }
.stat-card.on { background: #f0f5ff; }
.stat-card.on::after { content: ""; position: absolute; inset: 0 auto 0 0; width: 3px; background: var(--brand); }
.stat-card:focus-visible { outline: 2px solid var(--brand); outline-offset: -2px; }
.stat-card .num { font-size: var(--fs-display); font-weight: 700; line-height: 1.1; }
.stat-card .lbl { font-size: var(--fs-meta); color: var(--muted); margin-top: 5px; }
.stat-card.warn .num { color: var(--red); }
.stat-card.primary .num { color: var(--brand); }
.stat-card.amber .num { color: var(--amber); }
.stat-card.blue .num { color: #2563eb; }
@media (max-width: 1200px) { .stats-row { grid-template-columns: repeat(3, minmax(0, 1fr)); } .stat-card:nth-child(3) { border-right: 0; } .stat-card:nth-child(-n+3) { border-bottom: 1px solid var(--border); } }
@media (max-width: 800px) { .stats-row { grid-template-columns: repeat(2, minmax(0, 1fr)); } .stat-card { border-right: 1px solid var(--border); border-bottom: 1px solid var(--border); } .stat-card:nth-child(even) { border-right: 0; } .stat-card:nth-last-child(-n+2) { border-bottom: 0; } }

.card { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); margin-bottom: 16px; overflow: auto; }
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
.cal-start .cal-dot { background: var(--brand); }
.cal-deadline .cal-dot { background: var(--amber); }
.cal-overdue .cal-dot { background: var(--red); }
.cal-past .cal-dot { background: var(--red); }
.cal-past .cal-text { color: var(--red); font-weight: 600; }
.cal-more { color: var(--brand); font-weight: 600; cursor: default; }
.cal-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* 角色口径切换 */
.role-tabs { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; padding: 9px 12px; background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); }
.role-tabs-label { font-size: var(--fs-meta); color: var(--muted); margin-right: 4px; }
.role-tab { padding: 4px 10px; border-radius: 4px; border: 1px solid transparent; background: transparent; font: inherit; font-size: var(--fs-meta); cursor: pointer; color: #4b5563; transition: all .15s; }
.role-tab:hover { border-color: var(--brand); color: var(--brand); }
.role-tab.on { background: var(--brand); border-color: var(--brand); color: #fff; font-weight: 600; }
.role-tab:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; }

/* 日历空态 */
.cal-empty-banner { text-align: center; padding: 32px 16px; color: var(--muted); }
.cal-empty-icon { font-size: 40px; margin-bottom: 8px; }
.cal-empty-title { font-size: 15px; font-weight: 700; color: #374151; margin-bottom: 4px; }
.cal-empty-desc { font-size: 12px; }
</style>
