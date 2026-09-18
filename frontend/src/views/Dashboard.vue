<template>
  <div class="dashboard" v-loading="loading">
    <PageError v-if="!loading && loadError" title="看板加载失败" :message="loadError" @action="loadStats" />

    <template v-if="!loading && !loadError">
      <div class="filter-bar">
        <t-select v-model="filters.project_id" placeholder="全部项目" clearable filterable @change="applyFilters" style="width:220px">
          <t-option v-for="p in projectOptions" :key="p.id" :value="p.id" :label="p.name" />
        </t-select>
        <t-select v-model="filters.region" placeholder="全部区域" clearable @change="applyFilters" style="width:150px">
          <t-option v-for="r in regions" :key="r" :value="r" :label="r" />
        </t-select>
        <t-date-picker v-model="filters.month" mode="month" value-type="YYYY-MM" placeholder="全部月份" clearable @change="applyFilters" style="width:160px" />
        <span v-if="hasActiveFilters" class="filter-hint">已按此条件筛选全部卡片与趋势</span>
        <t-button v-if="hasActiveFilters" theme="default" variant="text" @click="resetFilters">清除筛选</t-button>
      </div>

      <!-- 空状态 -->
      <t-card v-if="stats.total === 0 && !hasActiveFilters" class="empty-card">
        <div class="empty-banner">
          <div class="empty-icon">📋</div>
          <div class="empty-title">暂无工单</div>
          <div class="empty-desc">系统已就绪。前往「新建工单」创建第一条，或在钉钉群里 <code>@机器人 创建工单：…</code> 快速录入。</div>
          <t-button theme="primary" @click="router.push('/create')">＋ 新建第一条工单</t-button>
        </div>
      </t-card>
      <div v-else-if="stats.total === 0" class="filter-empty">当前筛选条件下没有匹配的工单，请调整项目 / 区域 / 月份</div>
    </template>

    <template v-if="!loadError && stats.total > 0">
      <div class="management-lead">
        <div><h2>管理摘要</h2><p>先处理逾期与 P1 风险，再跟进执行和验收。</p></div>
        <t-button variant="outline" @click="goToList({})">查看全部工单</t-button>
      </div>
      <div class="card-row">
        <t-card v-for="s in statCards" :key="s.key" class="stat-card" :class="s.cls" hover @click="goCard(s)">
          <div class="stat-num" :style="{ color: s.color }">{{ s.value }}</div>
          <div class="stat-lbl">{{ s.label }}</div>
        </t-card>
      </div>

      <div class="section-kicker">时效与闭环</div>
      <div class="card-row">
        <t-card class="kpi-card">
          <t-statistic title="SLA 合规率" :value="stats.sla_compliance" suffix="%" :color="slaColor" />
          <div class="kpi-sub" :style="{color: slaColor}">{{ slaCompliance >= 90 ? '良好' : slaCompliance >= 70 ? '需关注' : '告警' }}</div>
        </t-card>
        <t-card class="kpi-card"><t-statistic title="MTTR 平均处理(天)" :value="stats.mttr_days ?? '—'" /></t-card>
        <t-card class="kpi-card"><t-statistic title="MTTA 响应(天)" :value="stats.mtta_days ?? '—'" /></t-card>
        <t-card class="kpi-card"><t-statistic title="SLA 违约数" :value="stats.overdue" :color="stats.overdue ? '#d54941' : undefined" /></t-card>
        <t-card class="kpi-card"><t-statistic title="闭环率" :value="stats.closed_rate" suffix="%" color="#2ba471" /></t-card>
      </div>

      <!-- 告警条 -->
      <t-card v-if="stats.overdue_items.length" class="alert-card" :bordered="false">
        <div class="alert-inner">
          <span class="alert-icon">🚨</span>
          <span class="alert-text">SLA 违约告警：{{ stats.overdue_items.length }} 条工单已超期<span v-if="p1Count">，P1 级 {{ p1Count }} 起触发三级升级</span></span>
          <div class="alert-items">
            <t-tag v-for="it in stats.overdue_items" :key="it.id" :theme="it.escalation_level >= 3 ? 'danger' : 'warning'" @click="goDetail(it.id)" style="cursor:pointer;margin:2px">
              {{ it.escalation_level >= 3 ? '🔴' : it.escalation_level >= 2 ? '🟠' : '🟡' }} {{ it.code }} · {{ it.person }} · 超{{ it.overdue_days }}天
            </t-tag>
          </div>
        </div>
      </t-card>

      <div class="section-kicker">需要处置</div>
      <div class="two-col">
        <t-card title="优先跟进" subtitle="按逾期、P1、截止时间排序" class="todo-card">
          <t-list :split="true">
            <t-list-item v-for="w in paginatedTodos" :key="w.id" @click="goDetail(w.id)" class="todo-item" :class="{overdue: w.status==='overdue'}">
              <t-list-item-meta>
                <template #title>
                  <t-tag size="small" :theme="statusTheme(w.status)">{{ statusLabel(w.status) }}</t-tag>
                  <span class="todo-title">{{ w.title }}</span>
                </template>
                <template #description>
                  <span class="todo-meta">{{ w.person }} · 截止 {{ w.deadline }}</span>
                  <t-tag v-if="w.escalation_level > 0" size="small" theme="warning" style="margin-left:8px">{{ escLabel[w.escalation_level] }}</t-tag>
                </template>
              </t-list-item-meta>
            </t-list-item>
            <t-list-item v-if="stats.todo_items.length === 0" class="todo-empty">
              🎉 暂无待办，所有工单已闭环
            </t-list-item>
          </t-list>
          <t-pagination
            v-if="stats.todo_items.length > todoPageSize"
            :current="todoPage"
            :page-size="todoPageSize"
            :total="stats.todo_items.length"
            :page-size-options="[5, 10, 20]"
            size="small"
            show-jumper
            @current-change="onTodoCurrentChange"
            @page-size-change="onTodoPageSizeChange"
            style="margin-top:12px; justify-content:center"
          />
        </t-card>

        <t-card title="风险来源与时效" class="dist-card">
          <div v-for="s in stats.source_dist" :key="s.code" class="dist-item" @click="goToList({ source_code: s.code })">
            <div class="dist-row">
              <span class="src-tag" :class="srcClass(s.code)">{{ s.name }}</span>
              <span class="dist-count">{{ s.count }} 条 · {{ s.pct }}%</span>
            </div>
            <t-progress :percentage="s.pct" :color="srcColor(s.code)" size="small" />
          </div>
          <t-divider />
          <div class="aging">
            <div class="aging-title">工单时效分布（创建→闭环）</div>
            <div class="aging-bar">
              <div class="aging-seg green" :style="{flex: agingTotal ? aging.d3/agingTotal : 0}">{{ aging.d3 || '' }}</div>
              <div class="aging-seg amber" :style="{flex: agingTotal ? aging.d7/agingTotal : 0}">{{ aging.d7 || '' }}</div>
              <div class="aging-seg orange" :style="{flex: agingTotal ? aging.d14/agingTotal : 0}">{{ aging.d14 || '' }}</div>
              <div class="aging-seg red" :style="{flex: agingTotal ? aging.o14/agingTotal : 0}">{{ aging.o14 || '' }}</div>
            </div>
            <div class="aging-axis"><span>≤3天</span><span>3-7天</span><span>7-14天</span><span>&gt;14天</span></div>
          </div>
        </t-card>
      </div>

      <div class="section-kicker">管理分析</div>
      <div class="two-col" style="--left:2; --right:1">
        <t-card title="月度趋势">
          <div ref="trendChart" style="height:240px"></div>
        </t-card>
        <t-card title="工单类型分布">
          <div ref="typeChart" style="height:240px"></div>
        </t-card>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, nextTick } from "vue";
import { useRouter } from "vue-router";
import { getDashboardStats, type DashboardStats } from "@/api/dashboard";
import { getTrends } from "@/api/pool";
import { getProjectsAll } from "@/api/config";
import { statusLabel, statusTheme, escLabel } from "@/utils/wo-display";
import PageError from "@/components/PageError.vue";
import * as echarts from "echarts/core";
import { LineChart, PieChart } from "echarts/charts";
import { GridComponent, TooltipComponent, LegendComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([LineChart, PieChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

const router = useRouter();
const stats = ref<DashboardStats>(empty());
const loading = ref(true);
const loadError = ref("");

const regions = ["华北", "华中", "华东", "华南", "西北", "西南", "东北"];
const projectOptions = ref<any[]>([]);
const filters = reactive<{ project_id: number | undefined; region: string | undefined; month: string | undefined }>({
  project_id: undefined,
  region: undefined,
  month: undefined,
});
const hasActiveFilters = computed(() => !!filters.project_id || !!filters.region || !!filters.month);

function statsParams() {
  const p: any = {};
  if (filters.project_id != null) p.project_id = filters.project_id;
  if (filters.region) p.region = filters.region;
  if (filters.month) p.month = filters.month;
  return p;
}
function trendParams() {
  const p: any = {};
  if (filters.project_id != null) p.project_id = filters.project_id;
  if (filters.region) p.region = filters.region;
  return p;
}
function listQuery(f: any = {}) {
  const q: any = { ...f };
  if (filters.project_id != null) q.project_id = filters.project_id;
  if (filters.region) q.region = filters.region;
  return q;
}
function applyFilters() { loadStats(); }
function resetFilters() {
  filters.project_id = undefined;
  filters.region = undefined;
  filters.month = undefined;
  loadStats();
}

function empty(): DashboardStats {
  return { total: 0, executing: 0, pending_verify: 0, overdue: 0, closed: 0, sla_compliance: 0,
    mttr_days: null, mtta_days: null, closed_rate: 0, aging: { d3: 0, d7: 0, d14: 0, o14: 0 },
    source_dist: [], overdue_items: [], todo_items: [] };
}

const statCards = computed(() => [
  { key: "total", label: "工单总数", value: stats.value.total, cls: "", color: "#0052d9", filter: {} },
  { key: "exec", label: "执行中", value: stats.value.executing, cls: "amber", color: "#e37318", filter: { status: "executing" } },
  { key: "overdue", label: "SLA 已违约", value: stats.value.overdue, cls: "red", color: "#d54941", filter: { status: "overdue" } },
  { key: "pending", label: "待验收", value: stats.value.pending_verify, cls: "blue", color: "#0052d9", filter: { status: "verifying" } },
  { key: "closed", label: "已闭环", value: stats.value.closed, cls: "green", color: "#2ba471", filter: { status: "closed" } },
]);

const p1Count = computed(() => stats.value.overdue_items.filter((i) => i.escalation_level >= 3).length);
const aging = computed(() => stats.value.aging);
const agingTotal = computed(() => Object.values(aging.value).reduce((a, b) => a + b, 0));
const slaCompliance = computed(() => stats.value.sla_compliance);
const slaColor = computed(() => slaCompliance.value >= 90 ? "#2ba471" : slaCompliance.value >= 70 ? "#e37318" : "#d54941");

// ── 待办分页 ──
const todoPage = ref(1);
const todoPageSize = ref(10);
const paginatedTodos = computed(() => {
  const s = (todoPage.value - 1) * todoPageSize.value;
  return stats.value.todo_items.slice(s, s + todoPageSize.value);
});
function onTodoCurrentChange(current: number) { todoPage.value = current; }
function onTodoPageSizeChange(pageSize: number) { todoPageSize.value = pageSize; todoPage.value = 1; }

const srcColorMap: Record<string, string> = { plan: "#0052d9", alert: "#d54941", meeting: "#e37318", manual: "#7c3aed" };
const srcClassMap: Record<string, string> = { plan: "src-plan", alert: "src-alert", meeting: "src-meeting", manual: "src-manual" };
const srcColor = (c: string) => srcColorMap[c] ?? "#8c8c8c";
const srcClass = (c: string) => srcClassMap[c] ?? "";

function goToList(f: any = {}) { router.push({ path: "/work-orders", query: listQuery(f) }); }
function goCard(s: any) {
  // 已闭环默认归档：看闭环记录页，其余状态卡仍跳主列表筛选
  if (s.key === "closed") router.push("/closed");
  else goToList(s.filter);
}
function goDetail(id: number) { router.push(`/work-orders/${id}`); }

const trendChart = ref<HTMLDivElement>();
const typeChart = ref<HTMLDivElement>();
let trendInstance: ReturnType<typeof echarts.init> | null = null;
let typeInstance: ReturnType<typeof echarts.init> | null = null;
function resizeCharts() { trendInstance?.resize(); typeInstance?.resize(); }
function disposeCharts() {
  trendInstance?.dispose(); typeInstance?.dispose();
  trendInstance = null; typeInstance = null;
}

async function initCharts() {
  await nextTick();
  try {
    const trends = await getTrends(trendParams());
    if (trendChart.value) {
      trendInstance?.dispose();
      const c = echarts.init(trendChart.value);
      trendInstance = c;
      c.setOption({
        tooltip: { trigger: "axis" },
        legend: { data: ["新增", "闭环", "逾期"], bottom: 0 },
        grid: { left: 40, right: 20, top: 10, bottom: 30 },
        xAxis: { type: "category", data: trends.trends.map((t: any) => t.month.slice(5)) },
        yAxis: { type: "value" },
        series: [
          { name: "新增", type: "line", data: trends.trends.map((t: any) => t.created), smooth: true, itemStyle: { color: "#2563eb" } },
          { name: "闭环", type: "line", data: trends.trends.map((t: any) => t.closed), smooth: true, itemStyle: { color: "#16a34a" } },
          { name: "逾期", type: "line", data: trends.trends.map((t: any) => t.overdue), smooth: true, itemStyle: { color: "#dc2626" } },
        ],
      });
    }
    if (typeChart.value) {
      typeInstance?.dispose();
      const c = echarts.init(typeChart.value);
      typeInstance = c;
      c.setOption({
        tooltip: { trigger: "item" },
        series: [{
          type: "pie", radius: ["40%", "70%"], center: ["50%", "50%"],
          data: trends.type_dist.map((t: any) => ({ name: t.name, value: t.count })),
          label: { formatter: "{b}\n{d}%" },
        }],
      });
    }
  } catch (e) { console.error(e); }
}

async function loadStats() {
  loading.value = true;
  loadError.value = "";
  try {
    stats.value = await getDashboardStats(statsParams());
  } catch (e: any) {
    loadError.value = e?.message || "请检查网络连接后重试";
    stats.value = empty();
  } finally {
    loading.value = false;
  }
  if (!loadError.value && stats.value.total > 0) await initCharts();
}

onMounted(async () => {
  window.addEventListener("resize", resizeCharts);
  try { projectOptions.value = await getProjectsAll(); } catch { /* 项目列表加载失败不影响看板 */ }
  loadStats();
});
onUnmounted(() => { window.removeEventListener("resize", resizeCharts); disposeCharts(); });
</script>

<style scoped>
.dashboard { display: flex; flex-direction: column; gap: 16px; }
.filter-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); padding: 10px 12px; box-shadow: var(--shadow); }
.filter-hint { font-size: 12px; color: var(--muted); margin-left: auto; }
.filter-empty { text-align: center; padding: 48px 16px; color: var(--muted); font-size: 14px; background: var(--card); border-radius: var(--radius); }
.management-lead { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding-top: 4px; }
.management-lead h2 { font-size: var(--fs-h1); line-height: 1.35; margin: 0; }
.management-lead p { color: var(--muted); font-size: var(--fs-meta); margin: 4px 0 0; }
.section-kicker { display: flex; align-items: center; gap: 8px; color: #4b5563; font-size: var(--fs-h2); font-weight: 700; margin: 4px 0 -8px; }
.section-kicker::before { content: ""; display: block; width: 3px; height: 14px; background: var(--brand); }

.empty-card .empty-banner { text-align: center; padding: 32px 20px; }
.empty-icon { font-size: 48px; }
.empty-title { font-size: var(--fs-h1); font-weight: 700; margin: 8px 0; }
.empty-desc { color: var(--muted); font-size: var(--fs-meta); margin-bottom: 16px; }
.empty-desc code { background: #f0f4ff; padding: 2px 6px; border-radius: 3px; }

/* ── 等宽卡片行（flexbox，自动平分） ── */
.card-row { display: flex; gap: 0; background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); overflow: hidden; }
.card-row > * { flex: 1; min-width: 0; }
.card-row :deep(.t-card) { border: 0; border-radius: 0; box-shadow: none; }
.card-row > * + * { border-left: 1px solid var(--border); }

/* 统计卡片 */
.stat-card { text-align: left; border-left: 3px solid var(--border); transition: background .15s; }
.stat-card:hover { background: #f8fafc; }
.stat-card.amber { border-left-color: var(--amber); }
.stat-card.red { border-left-color: var(--red); }
.stat-card.green { border-left-color: var(--green); }
.stat-card.blue { border-left-color: var(--blue); }
.stat-num { font-size: var(--fs-display); font-weight: 800; line-height: 1; }
.stat-lbl { font-size: var(--fs-meta); color: var(--muted); margin-top: 6px; }

/* KPI 卡片 */
.kpi-card { text-align: left; }
.kpi-sub { font-size: var(--fs-meta); margin-top: 4px; }

/* 告警条 */
.alert-card { background: #fff8f7; border: 1px solid #f0c5c2; box-shadow: none; }
.alert-inner { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.alert-icon { font-size: 20px; }
.alert-text { font-size: var(--fs-body); font-weight: 600; color: #a82820; }
.alert-items { display: flex; flex-wrap: wrap; gap: 4px; margin-left: auto; }

/* ── 双列布局（待办+来源 / 趋势+类型） ── */
.two-col { display: flex; gap: 16px; }
.two-col :deep(.t-card) { border: 1px solid var(--border); box-shadow: var(--shadow); }
.two-col > *:first-child { flex: var(--left, 3); min-width: 0; }
.two-col > *:last-child { flex: var(--right, 2); min-width: 0; }

/* 待办 */
.todo-card :deep(.t-card__body) { max-height: 500px; overflow-y: auto; }
.todo-item { cursor: pointer; border-radius: 6px; padding: 4px 8px; }
.todo-item:hover { background: #f5f7fa; }
.todo-item.overdue { background: #fef2f2; }
.todo-title { font-size: var(--fs-body); margin-left: 8px; }
.todo-meta { font-size: var(--fs-tag); color: var(--muted); }
.todo-empty { text-align: center; padding: 16px; color: var(--muted); }

/* 来源分布 */
.dist-item { padding: 6px 0; cursor: pointer; }
.dist-item:hover { background: #f5f7fa; border-radius: 4px; }
.dist-row { display: flex; justify-content: space-between; margin-bottom: 4px; font-size: var(--fs-body); }
.dist-count { font-weight: 600; }
.src-tag { display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: var(--fs-tag); font-weight: 700; }
.src-plan { background: #dbeafe; color: #1e40af; }
.src-alert { background: #fee2e2; color: #991b1b; }
.src-meeting { background: #fef3c7; color: #92400e; }
.src-manual { background: #e0e7ff; color: #3730a3; }

/* 时效 */
.aging { margin-top: 8px; }
.aging-title { font-size: var(--fs-meta); color: var(--muted); margin-bottom: 6px; }
.aging-bar { display: flex; height: 20px; border-radius: 4px; overflow: hidden; }
.aging-seg { display: flex; align-items: center; justify-content: center; font-size: var(--fs-tag); font-weight: 700; color: #fff; min-width: 0; transition: flex .3s; }
.aging-seg.green { background: var(--green); }
.aging-seg.amber { background: var(--amber); }
.aging-seg.orange { background: #ed7d2d; }
.aging-seg.red { background: var(--red); }
.aging-axis { display: flex; justify-content: space-between; font-size: 10px; color: var(--muted); margin-top: 4px; }
</style>
