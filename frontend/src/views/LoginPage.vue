<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-header">
        <div class="logo">◆</div>
        <h1>软工单闭环管理平台</h1>
        <p class="sub">新能源电站运维 · 工单系统</p>
      </div>

      <div class="login-body">
        <button class="btn-dingtalk" @click="doDingTalkLogin" :disabled="loading">
          <span class="dt-icon">𝚫</span>
          {{ loading ? "登录中…" : "钉钉账号一键登录" }}
        </button>

        <div class="divider"><span>开发模式</span></div>

        <select v-model="devUser" class="dev-select">
          <option v-for="u in devUsers" :key="u.id" :value="u">{{ u.name }} ({{ u.role }})</option>
        </select>
        <button class="btn-dev" @click="doDevLogin" :disabled="loading">
          {{ loading ? "登录中…" : "开发环境登录" }}
        </button>
      </div>

      <div class="login-footer">
        <span>北京协合运维风电技术有限公司</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter, useRoute } from "vue-router";
import { getDingTalkLoginUrl, dingtalkCallback, getPermissions } from "@/api/auth";
import { useUserStore } from "@/stores/user";
import http from "@/api/http";

const router = useRouter();
const route = useRoute();
const store = useUserStore();
const loading = ref(false);
const devUser = ref<any>(null);

const devUsers = [
  { id: 14, name: "admin", role: "admin" },
  { id: 11, name: "金惠良", role: "approver" },
  { id: 1, name: "王小宁", role: "executor" },
];

async function doDingTalkLogin() {
  loading.value = true;
  try {
    const redirect = (route.query.redirect as string) || "/";
    const { url } = await getDingTalkLoginUrl(redirect);
    window.location.href = url;
  } catch (e: any) {
    alert("获取登录链接失败：" + e.message);
    loading.value = false;
  }
}

async function doDevLogin() {
  if (!devUser.value) return;
  loading.value = true;
  try {
    // 开发环境：直接创建 token
    const res = await http.post("/auth/dev-login", {
      user_id: devUser.value.id,
      name: devUser.value.name,
      role: devUser.value.role,
    });
    store.setAuth(res.access_token, res.user);
    await loadPermissions();
    const redirect = (route.query.redirect as string) || "/";
    router.push(redirect);
  } catch (e: any) {
    alert("登录失败：" + e.message);
  } finally {
    loading.value = false;
  }
}

async function loadPermissions() {
  try {
    store.permissions = await getPermissions();
  } catch {
    // 权限加载失败不影响使用
  }
}

onMounted(async () => {
  // 钉钉 OAuth 回调
  const code = route.query.code as string;
  if (code) {
    loading.value = true;
    try {
      const redirect_path = (route.query.redirect_path as string) || "/";
      const res = await dingtalkCallback(code, redirect_path);
      store.setAuth(res.access_token, res.user);
      await loadPermissions();
      router.push(res.redirect_path || "/");
    } catch (e: any) {
      alert("钉钉登录失败：" + e.message);
    } finally {
      loading.value = false;
    }
  }
});
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
}
.login-card {
  width: 400px;
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.3);
  overflow: hidden;
}
.login-header {
  text-align: center;
  padding: 40px 40px 20px;
}
.logo {
  font-size: 48px;
  color: #2563eb;
  margin-bottom: 12px;
}
.login-header h1 {
  font-size: 22px;
  font-weight: 700;
  color: #1e293b;
  margin: 0;
}
.sub {
  font-size: 13px;
  color: #94a3b8;
  margin: 6px 0 0;
}
.login-body {
  padding: 20px 40px 32px;
}
.btn-dingtalk {
  width: 100%;
  padding: 14px;
  border: none;
  border-radius: 10px;
  background: #0089ff;
  color: #fff;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}
.btn-dingtalk:hover { background: #0074d9; }
.btn-dingtalk:disabled { opacity: 0.6; cursor: not-allowed; }
.dt-icon { font-size: 22px; }

.divider {
  display: flex;
  align-items: center;
  margin: 20px 0;
  color: #cbd5e1;
  font-size: 12px;
}
.divider::before, .divider::after {
  content: "";
  flex: 1;
  height: 1px;
  background: #e2e8f0;
}
.divider span { margin: 0 12px; }

.dev-select {
  width: 100%;
  padding: 10px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 14px;
  margin-bottom: 10px;
}
.btn-dev {
  width: 100%;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
  color: #64748b;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
}
.btn-dev:hover { background: #f1f5f9; }

.login-footer {
  text-align: center;
  padding: 16px;
  background: #f8fafc;
  font-size: 11px;
  color: #94a3b8;
}
</style>