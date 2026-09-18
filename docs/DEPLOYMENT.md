# 部署 Runbook · 工单管理平台

> 从零到 ACK 上线运行的全流程。按顺序执行。

## 0. 前置条件

- 阿里云账号，开通：ACK、RDS PostgreSQL、Tair/Redis、OSS、ALB
- 域名 + SSL 证书（ALB 可用免费证书）
- 钉钉企业内部应用（拿 AppKey/AppSecret/AgentId）+ OA审批模板 processCode
- 本地装好 docker、kubectl、helm

## 1. 准备镜像

> 构建上下文统一为**仓库根目录**（Dockerfile 内已按 `backend/`、`frontend/` 前缀 COPY）。

```bash
# 后端（内置 Node + dws CLI，用于钉盘/AI表格数据同步）
docker build -t registry.cn-hangzhou.aliyuncs.com/<命名空间>/wo-backend:0.6.0 -f docker/Dockerfile.backend .

# 前端
docker build -t registry.cn-hangzhou.aliyuncs.com/<命名空间>/wo-frontend:0.6.0 -f docker/Dockerfile.frontend .

# 推送
docker push registry.cn-hangzhou.aliyuncs.com/<命名空间>/wo-backend:0.6.0
docker push registry.cn-hangzhou.aliyuncs.com/<命名空间>/wo-frontend:0.6.0
```

> 在 ACK 控制台创建容器镜像服务（ACR）命名空间，替换 `<命名空间>`。
> 判断 Agent（wo-judgment-agent）v1 不部署，k8s.yaml 中已注释，镜像就绪后取消注释。

## 2. 创建云资源

| 资源 | 规格 | 说明 |
|---|---|---|
| RDS PostgreSQL 15 | 2C4G 100GB | 高可用版，创建库 `wo_closed_loop`，账号 `wo` |
| Tair Redis | 1GB | 标准版，ACK 内网直连 |
| OSS Bucket | - | 存附件，命名 `wo-attachments` |
| ACK 托管集群 | 2×4C8G ECS | Master 免费，Worker 按量 |
| ALB | 标准型 | SSL 终结，对接 Ingress |

## 3. 注入凭证（Secret）

> 配置项说明见 `backend/.env.production.example`。JWT_SECRET 生成：`openssl rand -hex 32`

```bash
kubectl create secret generic wo-secrets \
  --from-literal=DATABASE_URL='postgresql+psycopg://wo:<密码>@<RDS内网地址>:5432/wo_closed_loop' \
  --from-literal=REDIS_URL='redis://<Tair内网地址>:6379/0' \
  --from-literal=JWT_SECRET='<openssl rand -hex 32>' \
  --from-literal=APP_ENV='production' \
  --from-literal=AUTO_SEED='false' \
  --from-literal=DINGTALK_APP_KEY='<钉钉AppKey>' \
  --from-literal=DINGTALK_APP_SECRET='<钉钉AppSecret>' \
  --from-literal=DINGTALK_AGENT_ID='<企业内部应用AgentId，工作通知用>' \
  --from-literal=DINGTALK_ROBOT_WEBHOOK='<群机器人webhook，可选>' \
  --from-literal=DINGTALK_ROBOT_SECRET='<群机器人加签secret，可选>' \
  --from-literal=DINGTALK_OA_TEMPLATE_ID='<审批模板processCode>' \
  --from-literal=DINGTALK_CORP_ID='<企业ID>' \
  --from-literal=DINGTALK_LOGIN_REDIRECT_URI='https://你的域名/login' \
  --from-literal=FRONTEND_BASE_URL='https://你的域名' \
  --from-literal=LOGIN_ADMIN_ONLY='true' \
  --from-literal=DASHSCOPE_API_KEY='<百炼key，可选>' \
  --from-literal=CORS_ORIGINS='https://你的域名' \
  --from-literal=JUDGMENT_ENABLED='false'
```

### 3.1 dws 凭证（钉盘 / AI表格数据源，必需）

数据池两个自动来源（钉盘年度运营计划「非EAM」行、AI表格异常数据）通过
`dws`（dingtalk-workspace-cli）读取，镜像已内置，运行时需要**个人凭证包**：

```bash
# 1. 在 Mac 上导出凭证包（如已过期需先 dws login 重新授权）
DWS_DISABLE_KEYCHAIN=1 dws auth export -o ~/Documents/work/dws-auth.tar.gz

# 2. 注入集群（文件名必须是 dws-auth.tar.gz）
kubectl create secret generic wo-dws-auth \
  --from-file=dws-auth.tar.gz=$HOME/Documents/work/dws-auth.tar.gz
```

容器启动时自动 `dws auth import`（见 docker/entrypoint-backend.sh）。
**凭证 refresh token 约 30 天过期**，过期后重复上面两步并重启：

```bash
kubectl rollout restart deploy/wo-backend deploy/wo-worker deploy/wo-scheduler
```

验证：登录后调 `GET /api/pool/dws-status`，`authenticated: true` 即就绪；
手动触发入口：`POST /api/pool/sync-drive`（钉盘年度计划→非EAM工单）、
`POST /api/pool/sync-aitable`（AI表格异常→数据池）、`POST /api/pool/sync-full`（全链路）。

## 4. 部署到 ACK

```bash
# 改 docker/k8s.yaml 里镜像地址为本仓库真实地址
kubectl apply -f docker/k8s.yaml

# 等待就绪
kubectl rollout status deploy/wo-backend
kubectl rollout status deploy/wo-worker
kubectl rollout status deploy/wo-scheduler
kubectl rollout status deploy/wo-frontend
```

## 5. 数据库初始化（一次性）

```bash
# 进入后端 Pod 执行迁移；生产库不灌演示种子数据
kubectl exec -it deploy/wo-backend -- alembic upgrade head
```

## 6. 配置钉钉回调

钉钉开放平台 → 应用 → 事件订阅/回调：
- OA 审批回调地址：`https://你的域名/api/dingtalk/oa/callback`
- 群机器人回调地址：`https://你的域名/api/bot/command`

## 7. 验证

```bash
# 健康检查（应返回 200）
curl https://你的域名/health

# 安全头检查
curl -I https://你的域名/health | grep -iE 'x-frame|x-content-type|strict-transport'

# 钉钉凭证状态（需登录 token，或跳过）
# /api/dingtalk/status 需登录：先登录拿 token
# 期望：app_key/oa_template 等全 true

# 数据源就绪状态（需登录）
# GET /api/pool/dws-status → authenticated: true
```

浏览器访问 `https://你的域名`：
- 工作台显示数据
- /dingtalk 页凭证卡片全绿
- /config 页可改配置
- 派发工单后责任人钉钉收到「工作通知」卡片（需 DINGTALK_AGENT_ID + 应用工作通知权限）；配置了群机器人 webhook 则群内 @ 责任人

## 8. 运维

```bash
# 看日志
kubectl logs -f deploy/wo-backend
kubectl logs -f deploy/wo-worker

# 扩容
kubectl scale deploy/wo-backend --replicas=4

# 升级镜像
kubectl set image deploy/wo-backend backend=registry.../wo-backend:0.6.0
kubectl rollout status deploy/wo-backend

# 清空工单数据（保留配置）
kubectl exec -it deploy/wo-backend -- python -c \
  "from app.api.admin import clear_transactional_data; from app.core.database import SessionLocal; print(clear_transactional_data(SessionLocal()))"
```

### 8.1 日志落地策略（上线前需部署方确认）

后端日志两条路落：文件日志（`logs/app.log` 全量 + `logs/error.log` 仅 ERROR 带 traceback）+ 双写 stderr/stdout。
**当前问题**：`logs/` 写在 Pod 临时盘，Pod 重启/重调度即丢失，且 2 副本各记各的、无集中检索。二选一（推荐 b，省事）：

- **a. 挂持久卷采集文件**：给 `wo-backend` 挂 PVC 存 `logs/`，再接 Logtail 采文件。
- **b. 依赖 stdout 采集**：应用已设 `LOG_TO_STDERR=true` 双写 stdout，只需在 ACK 开通 SLS 日志服务，对 `wo-backend`/`wo-worker` 开 stdout 采集即可，文件日志仅作本地兜底。

> 未确认前 `kubectl logs` 能看到当次运行日志，但 Pod 重建后历史 error.log 会丢，故障回溯窗口有限。

### 8.2 用 request_id 串日志定位问题

每个请求带 `X-Request-Id`（响应头也回传），日志里 `[requestid] [name]` 的 requestid 即该值。定位「某次请求为什么 500」：

```bash
# 慢请求 / 错误（访问日志一行一条，含 method path status 耗时 ip uid）
kubectl logs deploy/wo-backend | grep -E '\[SLOW\]| 500 '

# 拿到 requestid 后，串出这次请求的完整日志（含 error.log 的 traceback）
kubectl logs deploy/wo-backend | grep <requestid>
```

慢请求阈值 `ACCESS_LOG_SLOW_MS`（默认 1000ms），超过访问日志升级为 `[SLOW] WARNING`。
> 多副本时一条请求只落其中一个 Pod，用 `kubectl logs -l app=wo-backend --prefix | grep <requestid>` 跨副本检索。

## 9. 监控（建议接入）

- ACK 控制台自带 Pod CPU/内存监控
- RDS/Tair 性能监控控制台
- 接入阿里云 ARMS（应用实时监控）看 API 慢请求和错误
- `/health` 接 SLB 健康检查
- 上线前并发压测：跑 `scripts/loadtest/`（见其 README），出 TPS / p95 延迟 / 错误率基线再定副本数

## 10. 备份

- RDS：开启自动备份（每日）+ 日志备份（WAL），保留 7 天
- OSS：开启版本控制或跨区域复制
- 配置变更：`config_definitions` 等表定期导出

## 安全清单

- [x] HTTPS + HSTS（nginx/ALB）
- [x] 安全响应头（nosniff/DENY/XSS/Referrer）
- [x] 速率限制（登录10/min、导入10/min、机器人30/min）
- [x] CORS 生产环境收紧到单域名
- [x] SQL 参数化（ORM，无拼接）
- [x] 密码 bcrypt 哈希
- [x] JWT 鉴权
- [x] 钉钉回调验签（生产需配 aes_key）
- [ ] 定期轮换 JWT_SECRET
