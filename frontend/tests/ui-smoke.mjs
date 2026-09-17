import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir } from "node:fs/promises";
import { chromium } from "playwright";

const base = "http://127.0.0.1:5189";
const screenshotDir = process.env.WO_UI_SCREENSHOT_DIR;
let server;
let browser;

before(async () => {
  server = spawn("./node_modules/.bin/vite", ["--host", "127.0.0.1", "--port", "5189", "--strictPort"], {
    cwd: new URL("..", import.meta.url).pathname,
    stdio: "ignore",
  });
  for (let i = 0; i < 60; i++) {
    try {
      const response = await fetch(base);
      if (response.ok) break;
    } catch { /* wait for Vite */ }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  browser = await chromium.launch({ channel: "chromium", headless: true });
});

after(async () => {
  await browser?.close();
  server?.kill();
});

async function pageFor(role = "admin", overrides = {}) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await context.addInitScript(() => localStorage.setItem("wo_token", "ui-smoke-token"));
  const page = await context.newPage();
  const calls = [];
  await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    calls.push({ method: request.method(), path: url.pathname, search: url.search });
    const path = url.pathname.replace(/^\/api/, "");
    const response = overrides[path] ?? defaultResponse(path, role);
    const wrapped = typeof response?.status === "number";
    await route.fulfill({
      status: wrapped ? response.status : 200,
      contentType: "application/json",
      body: JSON.stringify(wrapped ? response.body : response ?? []),
    });
  });
  return { page, calls, close: () => context.close() };
}

function defaultResponse(path, role) {
  if (path === "/auth/me") return { id: 1, name: "测试用户", role };
  if (path === "/auth/permissions") return {
    roles: [role],
    menu_groups: {
      "工作台": { "管理看板": { roles: [role] }, "我的工单": { roles: [role] } },
      "工单管理": { "工单列表": { roles: [role] }, "新建工单": { roles: [role] } },
    },
    actions: {},
  };
  if (path === "/dashboard/stats") return {
    total: 0, executing: 0, pending_verify: 0, overdue: 0, closed: 0,
    sla_compliance: 0, mttr_days: null, mtta_days: null, closed_rate: 0,
    aging: { d3: 0, d7: 0, d14: 0, o14: 0 }, source_dist: [], overdue_items: [], todo_items: [],
  };
  if (path === "/dashboard/mine") return {
    scope: "self", stats: { total: 2, pending: 0, executing: 2, verifying: 0, overdue: 0, need_backfill: 1 },
  };
  if (path === "/dashboard/calendar") return { items: [] };
  if (path === "/work-orders") return { items: [], total: 0, page: 1, page_size: 20 };
  if (path === "/work-orders/closed/list") return { items: [], total: 0, page: 1, page_size: 20 };
  if (path === "/pool/items") return { items: [], total: 0, page: 1, page_size: 20 };
  if (path === "/config/projects/all") return [{ id: 1, code: "PRJ-0001", name: "测试项目" }];
  if (path === "/config/work-order-types") return [{ id: 1, code: "routine", name: "常规" }];
  if (path === "/config/sources") return [{ code: "manual", name: "手动" }];
  if (path === "/config/users/all") return [{ id: 1, name: "测试用户", role }];
  if (path === "/config/person-project-map") return [{ project_id: 1, persons: [{ id: 1, is_default: true }] }];
  return [];
}

test("审批员可以进入有权限的首页", async () => {
  const { page, close } = await pageFor("approver");
  try {
    await page.goto(base + "/");
    await page.getByText("暂无工单", { exact: true }).waitFor({ timeout: 5000 });
    assert.equal(new URL(page.url()).pathname, "/");
  } finally { await close(); }
});

test("待回填统计卡使用与计数一致的筛选条件", async () => {
  const { page, calls, close } = await pageFor();
  try {
    await page.goto(base + "/my");
    await page.getByText("待回填", { exact: true }).waitFor();
    if (screenshotDir) {
      await page.setViewportSize({ width: 1440, height: 1100 });
      await mkdir(screenshotDir, { recursive: true });
      await page.locator(".my-page").screenshot({ path: `${screenshotDir}/my-dashboard.png` });
    }
    await page.getByText("待回填", { exact: true }).click();
    await page.waitForTimeout(150);
    const last = calls.filter((c) => c.path === "/api/work-orders").at(-1);
    assert.ok(last, "点击后应请求工单列表");
    assert.equal(new URLSearchParams(last.search).get("bucket"), "need_backfill");
  } finally { await close(); }
});

test("工单不存在时显示错误与返回入口", async () => {
  const { page, close } = await pageFor("admin", {
    "/work-orders/999": { status: 404, body: { detail: "工单不存在" } },
  });
  try {
    await page.goto(base + "/work-orders/999");
    await page.getByText("工单不存在").waitFor({ timeout: 5000 });
    assert.equal(await page.getByText("加载中…").count(), 0);
    assert.ok(await page.getByRole("button", { name: /返回列表/ }).count());
  } finally { await close(); }
});

test("新建工单缺审批人时阻止提交", async () => {
  const { page, calls, close } = await pageFor();
  try {
    await page.goto(base + "/create");
    await page.getByPlaceholder("一句话概括工单内容").waitFor();
    if (screenshotDir) {
      await page.setViewportSize({ width: 1440, height: 1200 });
      await mkdir(screenshotDir, { recursive: true });
      await page.locator(".wo-create").screenshot({ path: `${screenshotDir}/work-order-create.png` });
      await page.screenshot({ path: `${screenshotDir}/shell-create.png` });
    }
    await page.getByPlaceholder("一句话概括工单内容").fill("测试工单");
    await page.getByPlaceholder("具体要做什么、达到什么标准").fill("检查测试项目");
    await page.getByText("提交 → 发起钉钉OA审批").click();
    await page.getByText(/审批人.*必填|请.*审批人/).waitFor({ timeout: 3000 });
    assert.equal(calls.filter((c) => c.path === "/api/work-orders" && c.method === "POST").length, 0);
  } finally { await close(); }
});

test("新建页不预设项目和责任人", async () => {
  const { page, close } = await pageFor();
  try {
    await page.goto(base + "/create");
    await page.getByPlaceholder("一句话概括工单内容").waitFor();
    assert.equal(await page.locator(".wo-create .form-group").first().getByText("PRJ-0001 · 测试项目").count(), 0);
    assert.equal(await page.locator(".wo-create .ss-chip").count(), 0);
  } finally { await close(); }
});

test("项目编辑取消后新增表单不会保留旧项目", async () => {
  const { page, close } = await pageFor();
  try {
    await page.goto(base + "/projects");
    await page.getByRole("button", { name: "编辑" }).click();
    await page.getByRole("button", { name: "取消" }).click();
    await page.getByRole("button", { name: /新增项目/ }).click();
    await page.getByText("新增项目", { exact: true }).waitFor();
    assert.equal(await page.getByText("项目编码", { exact: true }).count(), 0);
    assert.equal(await page.getByPlaceholder("输入项目名称").inputValue(), "");
  } finally { await close(); }
});

test("看板接口失败时显示重试入口而非空数据引导", async () => {
  const { page, close } = await pageFor("admin", {
    "/dashboard/stats": { status: 503, body: { detail: "服务暂不可用" } },
  });
  try {
    await page.goto(base + "/");
    await page.getByText("看板加载失败").waitFor({ timeout: 5000 });
    assert.equal(await page.getByText("暂无工单", { exact: true }).count(), 0);
    assert.ok(await page.getByRole("button", { name: "重试" }).count());
  } finally { await close(); }
});

test("规则配置失败时展示统一错误态", async () => {
  const { page, close } = await pageFor("admin", {
    "/config/sources": { status: 503, body: { detail: "配置服务暂不可用" } },
  });
  try {
    await page.goto(base + "/config");
    await page.getByText("规则配置加载失败").waitFor({ timeout: 5000 });
    assert.ok(await page.getByRole("button", { name: "重试" }).count());
  } finally { await close(); }
});

test("OA 驱动的工单详情不展示本地流转按钮", async () => {
  const workOrder = {
    id: 3, code: "WO-0003", title: "测试审批单", status: "executing", source_code: "manual",
    priority: "P2", oa_id: "real-process-id", reason: "", action: "", conclusion: null,
    project_id: 1, project_name: "测试项目", person_id: 1, person_name: "测试用户",
    approver_id: 1, approver_name: "测试用户", type_id: 1, type_name: "常规",
    region: "华北", planned_start_date: null, deadline: "2026-09-20", completed_date: null,
    created_date: "2026-09-17", escalation_level: 0, overdue_days: 0,
    measure_progress: null, occurrences: [], alert_phase: null, metric_type: null,
  };
  const { page, close } = await pageFor("admin", { "/work-orders/3": workOrder });
  try {
    await page.goto(base + "/work-orders/3");
    await page.getByText("已由钉钉OA审批流驱动", { exact: false }).waitFor({ timeout: 5000 });
    assert.equal(await page.getByRole("button", { name: "开始执行" }).count(), 0);
  } finally { await close(); }
});

test("我的工单宽表只在卡片内横向滚动", async () => {
  const { page, close } = await pageFor();
  try {
    await page.goto(base + "/my");
    await page.getByText("待回填", { exact: true }).waitFor();
    for (const width of [1440, 1024, 768]) {
      await page.setViewportSize({ width, height: 900 });
      const dimensions = await page.evaluate(() => ({
        viewport: window.innerWidth,
        body: document.documentElement.scrollWidth,
        content: document.querySelector(".app-content").getBoundingClientRect().width,
        page: document.querySelector(".my-page").getBoundingClientRect().width,
      }));
      assert.ok(dimensions.body <= dimensions.viewport + 1, JSON.stringify(dimensions));
      assert.ok(dimensions.page <= dimensions.content + 1, JSON.stringify(dimensions));
    }
  } finally { await close(); }
});

test("主要页面在空数据响应下可打开且没有运行时异常", async () => {
  const { page, close } = await pageFor();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  try {
    for (const path of [
      "/my", "/work-orders", "/create", "/closed", "/pool", "/dingtalk",
      "/config", "/users", "/projects", "/sop", "/audit-log",
    ]) {
      await page.goto(base + path);
      await page.locator("h1").first().waitFor({ timeout: 5000 });
      await page.waitForTimeout(100);
      assert.deepEqual(errors.splice(0), [], path);
    }
  } finally { await close(); }
});

test("CSV 字段正确转义引号、逗号、换行和公式", async () => {
  const { page, close } = await pageFor();
  try {
    await page.goto(base + "/create");
    const csv = await page.evaluate(async () => {
      const { toCsv } = await import("/src/utils/csv.ts");
      return toCsv([["标题", "公式"], ['工单,"特殊"\n换行', "=1+1"]]);
    });
    assert.ok(csv.startsWith("\uFEFF"));
    assert.ok(csv.includes('"工单,""特殊""\n换行"'));
    assert.ok(csv.includes('"\'=1+1"'));
  } finally { await close(); }
});
