# PRS / Power Steering 安装与维护

当前 DPS 0.9 chart 内的 Power Steering 2.1.0 已部署，Helm revision 5，DPS 持久化 prs_enabled=true；headroom -15%，scheduler 5 秒。Config、Controller 与 SeaweedFS 4.18 Ready。拓扑 inactive、0 资源组/PRS domain；服务启用验收通过，动态功率闭环尚未运行。

## 必要配置与数据

- 主 values 为 ../values.yaml，同时开启 dps.prs.enabled 与 power-steering.enabled，关闭两级 chart 内建 PostgreSQL。
- databases.json / prepare-databases.sql 为独立 PG 三库配置；维护入口 ../../scripts/prepare-prs-databases.py。应用严格 TLS 说明见 database-prerequisites.md。
- s3-credentials.json / s3-secret.yaml 为独立持久 S3 密钥和 Kubernetes Secret。bucket dps-prs，禁止匿名读取；此内部 ClusterIP S3 使用 HTTP，由网络策略限定连接。
- dps-auth-secret.yaml 给真实 Controller 提供现有 dps-lab LDAP 凭据；Controller 严格验证 Core CA，不使用 alwaysAllow。
- runtime-images.json 记录固定镜像、archive 与 SHA256；../../scripts/stage-prs-images.py 导入 K3s containerd。
- enablement.json 记录本次授权、原设置、实际启用设置和归档位置；安装不依赖验收报告。
- SeaweedFS 3 PVC 数据在 ../../data/kubernetes/storage，组件日志为 emptyDir。三库和 S3 数据分开保存。

私密目录 700，凭据/Secret 文件 600。不要打印这些文件，修改 LDAP 用户密码后须更新 Controller Secret 并重启 Controller 以重新加载。

## 维护入口

以下在 /raid/vince/deploy 执行，按维护目的选择，不必全部重跑：

~~~bash
python3 dps-install/scripts/prepare-prs-databases.py
python3 dps-install/scripts/stage-prs-images.py
python3 dps-install/scripts/configure-prs.py
bash dps-install/scripts/prepare-namespace.sh
bash dps-install/scripts/install-dps.sh
bash dps-install/scripts/dps-login.sh
source dps-install/config/dps-env.sh
dpsctl --no-retry settings list
~~~

已有数据库的 PRS 全局设置不会被 Helm values 自动覆盖。本次已执行 settings update --set prs_enabled=true；仅核对状态时读取 settings list 即可。Scheduler 周期之间 idle 正常，应结合 iteration_count、next_run_at、last_error 核对。

若未来需暂停 PRS 调度功能，可经登录执行 dpsctl --no-retry settings update --set prs_enabled=false；这是操作说明，本次保持 true。完整组件卸载涉及 Helm、持久卷和数据库，应先备份并另行审查。

~~~bash
bash dps-install/scripts/postgresql-backup.sh
bash dps-install/scripts/postgresql-backup-prs.sh
~~~

四个数据库备份位于 ../../data/postgresql-backups。脚本校验 custom dump 目录；不覆盖恢复运行数据库。S3 PVC 保留实际运行数据，数据库 dump 不包含 S3 对象。

## 证据位置

当前部署验收在 /raid/vince/deploy/verification/reports/prs-installation.json（35/35），脚本仅在 verification/scripts。初次失败、网络修复和全部操作时间在 /raid/vince/deploy/installstep.md；旧材料在 verification/archive/prs-enablement。拓扑激活和自动 BMC 功率控制属于后续操作。
