# 部署 Runbook · 软工单闭环管理系统

> 从零到 ACK 上线运行的全流程。按顺序执行。

## 0. 前置条件

- 阿里云账号，开通：ACK、RDS PostgreSQL、Tair/Redis、OSS、ALB
- 域名 + SSL 证书（ALB 可用免费证书）
- 钉钉企业内部应用（拿 AppKey/AppSecret/AgentId）+ OA审批模板 processCode
- 本地装好 docker、kubectl、helm

## 1. 准备镜像

```bash
# 后端
docker build -t registry.cn-hangzhou.aliyuncs.com/<命名空间>/wo-backend:0.5.0 -f docker/Dockerfile.backend .

# 前端
docker build -t registry.cn-hangzhou.aliyuncs.com/<命名空间>/wo-frontend:0.5.0 -f docker/Dockerfile.frontend .

# 推送
docker push registry.cn-hangzhou.aliyuncs.com/<命名空间>/wo-backend:0.5.0
docker push registry.cn-hangzhou.aliyuncs.com/<命名空间>/wo-frontend:0.5.0
```

> 在 ACK 控制台创建容器镜像服务（ACR）命名空间，替换 `<命名空间>`。

## 2. 创建云资源

| 资源 | 规格 | 说明 |
|---|---|---|
| RDS PostgreSQL 15 | 2C4G 100GB | 高可用版，创建库 `wo_closed_loop`，账号 `wo` |
| Tair Redis | 1GB | 标准版，ACK 内网直连 |
| OSS Bucket | - | 存附件，命名 `wo-attachments` |
| ACK 托管集群 | 2×4C8G ECS | Master 免费，Worker 按量 |
| ALB | 标准型 | SSL 终结，对接 Ingress |

## 3. 注入凭证（Secret）

```bash
kubectl create secret generic wo-secrets \
  --from-literal=DATABASE_URL='postgresql+psycopg://wo:<密码>@<RDS内网地址>:5432/wo_closed_loop' \
  --from-literal=REDIS_URL='redis://<Tair内网地址>:6379/0' \
  --from-literal=JWT_SECRET='<随机64字符>' \
  --from-literal=DINGTALK_APP_KEY='<钉钉AppKey>' \
  --from-literal=DINGTALK_APP_SECRET='<钉钉AppSecret>' \
  --from-literal=DINGTALK_AGENT_ID='<AgentId>' \
  --from-literal=DINGTALK_OA_TEMPLATE_ID='<审批模板processCode>' \
  --from-literal=DINGTALK_CORP_ID='<企业ID>' \
  --from-literal=DASHSCOPE_API_KEY='<百炼key，可选>' \
  --from-literal=CORS_ORIGINS='https://你的域名' \
  --from-literal=APP_ENV='production'
```

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
# 进入后端 Pod 执行迁移 + 种子
kubectl exec -it deploy/wo-backend -- alembic upgrade head
kubectl exec -it deploy/wo-backend -- python -m app.seed
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

# 钉钉凭证状态
curl https://你的域名/api/dingtalk/status
# 期望：app_key/oa_template 等全 true
```

浏览器访问 `https://你的域名`：
- 工作台显示数据
- /dingtalk 页凭证卡片全绿
- /config 页可改配置
- 派发工单后钉钉收到通知/OA审批

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

## 9. 监控（建议接入）

- ACK 控制台自带 Pod CPU/内存监控
- RDS/Tair 性能监控控制台
- 接入阿里云 ARMS（应用实时监控）看 API 慢请求和错误
- `/health` 接 SLB 健康检查

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
- [ ] 钉钉回调验签（生产需配 aes_key，当前简化）
- [ ] 定期轮换 JWT_SECRET
