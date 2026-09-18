# v0.7.0 正式上线清单（云效 / ACK）

本包为源码部署包；当前仓库未发现既有云效流水线定义，已按已有 ACK + ACR 架构整理。云效流水线只需依序执行本清单命令，所有实际域名、ACR 命名空间、ACK 上下文和密钥均由部署方在云效变量/凭据库注入，绝不写入仓库或包中。

## 1. 云效变量与凭据

非敏感变量：`ACR_REGISTRY`、`ACR_NAMESPACE`、`IMAGE_TAG`（建议 Git commit SHA）、`KUBE_CONTEXT`、`DEPLOY_DOMAIN`。

受保护凭据：ACR 登录凭据、kubeconfig、RDS/Tair 连接、JWT 随机密钥、钉钉 AppKey/AppSecret/CorpId/OA 模板、OSS 访问密钥、dws 凭据包。先由凭据库创建/更新 `wo-secrets` 与可选 `wo-dws-auth`；不得执行会用示例值覆盖 Secret 的命令。

必须设定：`APP_ENV=production`、`AUTO_SEED=false`、`NAME_LOGIN_ENABLED=false`、`DEV_LOGIN_ENABLED=false`、`AUTO_WORKORDER_IMPORT_ENABLED=false`、`DINGTALK_LOGIN_REDIRECT_URI=https://<正式域名>/login`、`CORS_ORIGINS=https://<正式域名>`。

## 2. 云效构建步骤

```bash
docker build -t "$ACR_REGISTRY/$ACR_NAMESPACE/wo-backend:$IMAGE_TAG" -f docker/Dockerfile.backend .
docker build -t "$ACR_REGISTRY/$ACR_NAMESPACE/wo-frontend:$IMAGE_TAG" -f docker/Dockerfile.frontend .
docker push "$ACR_REGISTRY/$ACR_NAMESPACE/wo-backend:$IMAGE_TAG"
docker push "$ACR_REGISTRY/$ACR_NAMESPACE/wo-frontend:$IMAGE_TAG"
```

部署前将 `docker/k8s.yaml` 内两类镜像从 `latest` 改为同一不可变 `IMAGE_TAG`，再执行 `kubectl apply -f docker/k8s.yaml`。迁移用 `kubectl exec deploy/wo-backend -- alembic upgrade head`，生产禁止执行 seed。

## 3. 上线前数据清场

先完成 RDS 快照和 `pg_dump -Fc`，校验备份文件非空。将备份文件放入后端 Pod 可见路径后，先盘点，再执行：

```bash
PYTHONPATH=/app python /app/scripts/prelaunch_workorder_cleanup.py
PYTHONPATH=/app python /app/scripts/prelaunch_workorder_cleanup.py --apply --backup-file /backup/wo-before-v0.7.0.dump
```

保留已闭环工单，以及具有真实钉钉 OA 实例（非 `OA-` 本地占位号）且未终态的工单；删除其余工单。历史数据池不作为正式业务入口，不会在菜单中出现。

## 4. 验收与回滚

- 所有 Deployment rollout 成功；`/health` 返回 200。
- 登录页只出现“钉钉账号一键登录”；直接请求 `/api/auth/dev-login` 返回 403。
- 左侧菜单不显示“钉钉集成”；OA 回调仍可用。
- 数据池不出现在正式菜单；后续从“工单列表”的直接导入入口按确认范围导入，核对只产生确认范围内的工单。
- 失败时将镜像 tag 回退到上一个已验证 tag，并恢复清场前 RDS 备份；不要把 `latest` 当回滚点。
