# 独立 PostgreSQL（DPS 0.9 前置依赖）

已部署官方 PostgreSQL 17.11，独立于 DPS Helm release。Compose 项目和容器名为
`dps-postgresql`，镜像以 digest 固定在 `compose.yaml`。本次未安装 DPS，未运行 DPS migration。数据库保持原有独立服务；物理机原生 K3s 已 Ready，原生 Pod 到数据库连接已验收通过。

## 接入信息

- 地址：`10.6.131.43:15432`；数据库：`dps`；应用角色：`dps`。
- 专用随机密码：`/raid/vince/deploy/dps-install/config/postgresql-credentials.json`（0600）。
  `postgres` 管理密码也存放在该文件；管理角色仅通过容器内部 Unix socket 管理。
- 数据持久化：`/raid/vince/deploy/dps-install/data/postgresql`，不删除、不重建该目录。
- TLS：`verify-full`；公开 CA：`/raid/vince/deploy/dps-install/config/postgresql-ca.crt`。
  服务器证书 SAN 包含 IP 10.6.131.43 和 DNS L20-12/l20-12，CA 与服务器证书有效期 730 天。
  CA 私钥只在 `authority/ca.key`（0600）留存；不分发到 DPS Pod。
- 应用角色不是 superuser，无创建数据库/角色权限；拥有 dps 数据库及 public schema，
  已通过事务内 schema/table 创建、写入、删除和 rollback 验证 migration 所需基本权限。
- 应用连接必须使用 TLS 和 SCRAM 密码认证；允许来源仅包括本机管理 IP、
  原生 K3s 接入使用宿主机管理 IP 10.6.131.43 和 Pod 网段 10.42.0.0/16；
  PostgreSQL 自身 Docker 网段为 172.30.90.0/24。旧集群 Docker 网段授权已从 pg_hba.conf 删除并成功 reload。
  当前接入仍要求 TLS 与专用角色认证，原生 Pod 的 verify-full、TLS 1.3、SQL 与事务内 DDL 回滚均通过。
- PostgreSQL `max_connections=200`，覆盖当前 chart 默认 Core 连接池 100；后续增加组件需再检查容量。

## 启停和状态（在远程 L20-12 执行）

```bash
bash /raid/vince/deploy/dps-install/scripts/postgresql-start.sh
bash /raid/vince/deploy/dps-install/scripts/postgresql-status.sh
bash /raid/vince/deploy/dps-install/scripts/postgresql-stop.sh
```

`restart: unless-stopped` 在 Docker/主机重启后恢复未手动停止的容器。
停止脚本仅停止容器，不清空持久化数据。启动脚本不会运行 SDK 或安装 DPS。
`10-init-dps.sql` 仅对空 PGDATA 的首次初始化执行；修改密码须同时更新数据库和 Secret，
修改初始化文件不改变已经初始化的数据库。

## Kubernetes 接入（由前置依赖流程创建 Secret）

交付文件：

- `../postgresql-secret.yaml`（0600）：Secret `dps-postgresql`，
  `database-password` 与 `password` 键均保存同一应用密码。
  Core 实际读取 `global.postgresql.auth.secretKeys.passwordKey`；
  `userPasswordKey` 留作 chart 兼容字段。
- `../postgresql-ca-secret.yaml`：Secret `dps-postgresql-ca`，键 `ca.crt`。
- `../postgresql-values.yaml`：仅数据库相关 overlay，显式禁用内置 PostgreSQL、
  `dps.prs` 与 `power-steering`，配置 verify-full 及 CA 挂载。

上述 Secret 已恢复到原生 `dps-l20-12` context 的 dps namespace，原生 Pod 接入验证已通过；项目 kubeconfig
为 `/raid/vince/deploy/dps-install/config/kubernetes/kubeconfig.yaml`。
完整 `config/values.yaml` 已合并数据库配置及 BMC CA 挂载。后续修改数据库 overlay 时，
`dps.secrets` 是列表，不能覆盖已有 BMC CA 等挂载。
文件本身供后续安装使用；单独应用 overlay 不代表完成 DPS 部署。

## 备份与恢复

已提供可执行备份脚本，输出为权限 0600 的 custom-format dump。
备份保存在数据交付目录，属于实际恢复资料，不归为仅验证日志。

```bash
bash /raid/vince/deploy/dps-install/scripts/postgresql-backup.sh
```

该脚本使用容器内 postgres 管理角色的 peer 认证，不在命令行传递密码。
当前仅备份应用数据库；角色密码由 0600 凭据文件管理。不要公开备份或凭据。

以下为恢复到新数据库的示例，未自动执行。先检查 dump，再选择不存在的新数据库名；
不覆盖运行中的 dps 数据库。应用切换或正式恢复应先停止 DPS 写入并保留原数据库。

```bash
BACKUP=/raid/vince/deploy/dps-install/data/postgresql-backups/dps-YYYYMMDDTHHMMSSZ.dump
RESTORE_DB=dps_recovery_YYYYMMDD
docker exec -i -u postgres dps-postgresql pg_restore --list < "$BACKUP"
docker exec -u postgres dps-postgresql createdb -U postgres -O dps "$RESTORE_DB"
docker exec -i -u postgres dps-postgresql pg_restore -U postgres --dbname "$RESTORE_DB" --no-owner --role=dps --exit-on-error < "$BACKUP"
docker exec -u postgres dps-postgresql psql -X -U postgres -d "$RESTORE_DB" -c '\dt'
```

完成应用安装后，应按实际 schema 和数据再次验证备份/恢复。
CA 与服务器证书到期前需要续期；保留同一 CA 可避免修改客户端信任。轮换 CA 时同步更新 Kubernetes CA Secret。

## 验证资料

仅验证脚本为 `/raid/vince/deploy/verification/scripts/postgres-verify.py`。
报告和日志位于 `verification/reports/postgres-host-verification.json`、
`verification/logs/postgres-host-verification.log`，DPS 安装不读取它们。
当前 host 路径密码认证、TLS 证书校验、DDL 权限、拒绝错误密码和拒绝非 TLS 均通过。
物理机原生 K3s 已 Ready，19 项前置验收全部通过。实际原生 Pod 到 PostgreSQL 17.11 使用
TLS 1.3 和 verify-full，数据库身份与事务内 DDL 回滚成功。以
`verification/reports/prerequisite-check.json` 的时间、context `dps-l20-12` 和节点 `l20-12`
为当前证据，日志见 `verification/logs/native-k3s-prerequisite-check.log`。测试资源已清理；旧集群中的 Pod 检查仅为历史证据。
DPS migration 需 DPS 安装后验证。
