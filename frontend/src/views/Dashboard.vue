<template>
  <div class="dashboard" v-loading="loading">
    <!-- 空状态 -->
    <t-card v-if="!loading && stats.total === 0" class="empty-card">
      <div class="empty-banner">
        <div class="empty-icon">📋</div>
        <div class="empty-title">暂无工单</div>
        <div class="empty-desc">系统已就绪。前往「新建工单」创建第一条，或在钉钉群里 <code>@机器人 创建工单：…</code> 快速录入。</div>
        <t-button theme="primary" @click="router.push('/create')">＋ 新建第一条工单</t-button>
      </div>
    </t-card>

    <template v-if="stats.total > 0">
      <!-- 统计卡片 -->
      <div class="equal-row stats-row">
        <t-card v-for="s in statCards" :key="s.key" class="stat-card" :class="s.cls" hover @click="goToList(s.filter)">
          <div class="stat-num" :style="{ color: s.color }">{{ s.value }}</div>
          <div class="stat-lbl">{{ s.label }}</div>
        </t-card>
      </div>

      <!-- SLA 指标 -->
      <div class="equal-row kpi-row">
        <t-card class="kpi-card">
          <div class="kpi-ring">
            <t-statistic title="SLA 合规率" :value="stats.sla_compliance" suffix="%" :color="slaColor" />
            <div class="kpi-sub" :style="{color: slaColor}">{{ slaCompliance >= 90 ? '良好' : slaCompliance >= 70 ? '需关注' : '告警' }}</div>
          </div>
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

      <t-row :gutter="16" class="main-row">
        <!-- 待办 -->
        <t-col :span="6" :lg="6">
          <t-card title="📋 待办工单" :subtitle="`共 ${stats.todo_items.length} 条`" class="todo-card">
            <t-list>
              <t-list-item v-for="w in stats.todo_items" :key="w.id" @click="goDetail(w.id)" class="todo-item" :class="{overdue: w.status==='overdue'}">
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
            </t-list>
          </t-card>
        </t-col>

        <!-- 来源分布 + 时效 -->
        <t-col :span="6" :lg="6">
          <t-card title="📊 来源分布" class="dist-card">
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
        </t-col>
      </t-row>

    <!-- 趋势图表 -->
    <t-row :gutter="16" style="margin-top:16px">
      <t-col :span="8">
        <t-card title="月度趋势">
          <div ref="trendChart" style="height:240px"></div>
        </t-card>
      </t-col>
      <t-col :span="4">
        <t-card title="工单类型分布">
          <div ref="typeChart" style="height:240px"></div>
        </t-card>
      </t-col>
    </t-row>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, nextTick } from "vue";
import { useRouter } from "vue-router";
import { getDashboardStats, type DashboardStats } from "@/api/dashboard";
import { getTrends } from "@/api/pool";
import { statusLabel, statusTheme, escLabel } from "@/utils/wo-display";
import * as echarts from "echarts";

const router = useRouter();
const stats = ref<DashboardStats>(empty());
const loading = ref(true);

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

const srcColorMap: Record<string, string> = { plan: "#0052d9", alert: "#d54941", meeting: "#e37318", manual: "#7c3aed" };
const srcClassMap: Record<string, string> = { plan: "src-plan", alert: "src-alert", meeting: "src-meeting", manual: "src-manual" };
const srcColor = (c: string) => srcColorMap[c] ?? "#8c8c8c";
const srcClass = (c: string) => srcClassMap[c] ?? "";

function statusTheme(s: string): any {
  return ({ pending: "default", approving: "primary", dispatched: "warning", executing: "primary",
    verifying: "warning", closed: "success", overdue: "danger", rejected: "default" } as any)[s] || "default";
}

function goToList(f: any) { router.push({ path: "/work-orders", query: f }); }
function goDetail(id: number) { router.push(`/work-orders/${id}`); }

const trendChart = ref<HTMLDivElement>();
const typeChart = ref<HTMLDivElement>();

async function initCharts() {
  await nextTick();
  try {
    const trends = await getTrends();
    if (trendChart.value) {
      const c = echarts.init(trendChart.value);
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
      const c = echarts.init(typeChart.value);
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

onMounted(async () => {
  try { stats.value = await getDashboardStats(); }
  catch (e) { console.error(e); }
  finally { loading.value = false; }
  await nextTick();
  initCharts();
});
</script>

<style scoped>
.dashboard { display: flex; flex-direction: column; gap: 16px; }

.empty-card .empty-banner { text-align: center; padding: 32px 20px; }
.empty-icon { font-size: 48px; }
.empty-title { font-size: var(--fs-h1); font-weight: 700; margin: 8px 0; }
.empty-desc { color: var(--muted); font-size: var(--fs-meta); margin-bottom: 16px; }
.empty-desc code { background: #f0f4ff; padding: 2px 6px; border-radius: 3px; }

.stats-row .stat-card { text-align: center; border-left: 3px solid var(--border); transition: all .15s; }
.stat-card.amber { border-left-color: var(--amber); }
.stat-card.red { border-left-color: var(--red); }
.stat-card.green { border-left-color: var(--green); }
.stat-num { font-size: var(--fs-display); font-weight: 800; line-height: 1; }
.stat-lbl { font-size: var(--fs-meta); color: var(--muted); margin-top: 6px; }

.kpi-card { text-align: center; }
.kpi-sub { font-size: var(--fs-meta); margin-top: 4px; }

.alert-card { background: linear-gradient(90deg, #fbe5e3, #fff); border: 1px solid #f5b3b0; }
.alert-inner { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.alert-icon { font-size: 20px; }
.alert-text { font-size: var(--fs-body); font-weight: 600; color: #a82820; }
.alert-items { display: flex; flex-wrap: wrap; gap: 4px; margin-left: auto; }

.main-row { margin-top: 0; }
.todo-item { cursor: pointer; border-radius: 6px; padding: 4px 8px; }
.todo-item:hover { background: #f5f7fa; }
.todo-item.overdue { background: #fef2f2; }
.todo-title { font-size: var(--fs-body); margin-left: 8px; }
.todo-meta { font-size: var(--fs-tag); color: var(--muted); }

.dist-item { padding: 6px 0; cursor: pointer; }
.dist-item:hover { background: #f5f7fa; border-radius: 4px; }
.dist-row { display: flex; justify-content: space-between; margin-bottom: 4px; font-size: var(--fs-body); }
.dist-count { font-weight: 600; }
.src-tag { display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: var(--fs-tag); font-weight: 700; }
.src-plan { background: #dbeafe; color: #1e40af; }
.src-alert { background: #fee2e2; color: #991b1b; }
.src-meeting { background: #fef3c7; color: #92400e; }
.src-manual { background: #e0e7ff; color: #3730a3; }

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
