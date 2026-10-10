# 安装、拓扑接入与维护脚本

所有脚本在远端 `L20-12` 的 `/raid/vince/deploy` 执行。配置与包位于 `dps-install/config`、`packages`，持久数据位于 `data`，实际操作记录为根目录 `installstep.md`。原生物理节点 K3s 已运行；DPS 0.9 Core/Agent/UI 已通过手动 Helm 安装。2026-10-10 上午（Asia/Shanghai）完成独立 LDAP 接入，18 项目录检查通过；10:52:29 的 DPS 身份/授权/会话 API 验收为 28/28。2026-10-10（Asia/Shanghai）PRS 已通过手动 Helm 升级启用，当前 release 为 revision 5、deployed，9 个 workload Ready。17:05:41 的 PRS 验收为 35/35，覆盖部署、实际 Pod 严格数据库 TLS、S3、Controller 的 LDAP/DPS TLS 连接与登录回归。DPS 已持久化 `prs_enabled=true`、headroom `-15%` 和 scheduler `5 秒`；实际 PowerSteering 为 2.1.0，SeaweedFS 为 4.18。

| 脚本 | 用途 |
|---|---|
| `install-tools.py` | 官方下载、SHA256/版本校验，原子安装固定 Helm、kubectl |
| `install-dpsctl.sh` | 从固定官方镜像提取并安装 dpsctl 0.9 |
| `install-kubernetes.sh` | 安装或核对物理机原生 K3s 1.34.12+k3s1、systemd 和项目数据目录 |
| `refresh-kubeconfig.py` | 生成权限 600 的项目 kubeconfig，context 为 `dps-l20-12` |
| `kubernetes.sh status/start/stop` | 通过 systemctl 维护 K3s，保留持久数据 |
| `postgresql-start.sh`、`postgresql-status.sh`、`postgresql-stop.sh` | 独立 PostgreSQL Compose 启停与状态 |
| `postgresql-backup.sh` | 将 DPS 数据库备份到 `data/postgresql-backups`，权限 600 |
| `prepare-prs-databases.py` | 在独立 PostgreSQL 中准备 PRS 的三个数据库、dps 角色权限和限定来源的 hostssl SCRAM 规则，保存必要数据库输入 |
| `postgresql-backup-prs.sh` | 将 PRS 的三个数据库分别备份为权限 600 的 custom dump，保留 DPS 数据库的独立备份入口 |
| `prepare-ldap.py` | 从固定 runtime.tar 加载镜像，准备独立 LDAP 配置、初始化账号、LDAPS TLS 和 bind/CA Secret；已有目录不重置 |
| `build-ldap.sh` | 可选源码重建：用固定 Debian 13 基础镜像构建 OpenLDAP 2.6.10；镜像 ID 变更后先审查 deployment 固定 ID |
| `ldap-start.sh`、`ldap-status.sh`、`ldap-stop.sh` | 独立 OpenLDAP Compose 启停与状态，保留 `data/ldap` |
| `ldap-backup.sh` | 将目录备份为 `data/ldap-backups` 中权限 600 的 LDIF |
| `prepare-ldap-client-tls.py` | 准备独立 LDAP clientAuth 证书和 client TLS Secret，满足 DPS 0.9 Core 的证书/私钥配置要求 |
| `configure-ldap-auth.py` | 检查 LDAP Ready，调用客户端证书准备，配置 LDAP values、只读 bind 与完整 CA/client TLS 投射卷，并一次性轮换 JWT 签名身份 |
| `dps-login.sh` | 从私密账户文件读取真实 LDAP 用户密码，通过标准输入执行 CLI 登录 |
| `prepare-certificates.py` | 准备稳定 TLS/JWT/外部 Secret，拒绝不完整或不匹配的已有证书 |
| `prepare-namespace.sh` | 用明确 context 准备 namespace、Secret 和远端域名解析 |
| `stage-runtime-images.py` | 通过原生 `k3s ctr` 预置固定 digest 镜像，包括 migration 的 PostgreSQL 客户端 |
| `configure-prs.py` | 配置 DPS PRS 与 PowerSteering 开关、三库严格 TLS、内部 S3、LDAP DPS 凭据 Secret 和所需持久卷 |
| `stage-prs-images.py` | 根据 `config/prs/runtime-images.json` 将固定 PRS/PowerSteering 与 SeaweedFS 镜像预置到原生 K3s |
| `install-dps.sh` | 校验保存的 chart、原生节点和外部数据库范围后执行显式 Helm upgrade --install |
| `register-devices.sh` | 缺少时注册 GB300 33kW、0.95 效率电源架设备；存在且一致时不写，配置不同则拒绝覆盖 |
| `import-topology.sh` | 注册设备、校验、首次导入 DPS 0.9 拓扑并核验 72 条 Agent 关联；保留 inactive，同名拓扑拒绝重复导入 |
| `update-topology.sh` | 使用官方 API 与当前 hash 校验更新并回读 72 条关联；关联已一致时跳过写入，不用 force，不激活拓扑 |

常规 LDAP 接入顺序为 prepare-ldap.py → ldap-start.sh → ldap-status.sh → configure-ldap-auth.py。准备 PRS 时继续执行 prepare-prs-databases.py → configure-prs.py → prepare-namespace.sh → stage-runtime-images.py → stage-prs-images.py → install-dps.sh → dps-login.sh。运行时全局 PRS 开关的实际设置记录在根目录 installstep.md。常规流程复用保存的固定 LDAP 运行镜像；build-ldap.sh 是可选重建入口。OpenLDAP 与 PostgreSQL 独立于 DPS Helm release，只读 bind 账号与 UI 用户分开。

PRS 配置已启用 DPS PRS 和 PowerSteering 2.1.0，使用三个独立数据库与内部 SeaweedFS 4.18 S3。拓扑保持 inactive，当前无资源组和 PRS domain；组件部署与接口检查不代表动态功率控制已经验证。

安装入口已执行成功；重复 `install-dps.sh` 会执行 Helm upgrade，日常查看状态不需运行该脚本。首次导入和更新均读取 `config/topology-4rack-dps09.json`，不会读取验证报告、重置拓扑或赋予功率策略。

```bash
cd /raid/vince/deploy
source dps-install/config/dps-env.sh
kubectl --context dps-l20-12 -n dps get pods,pvc
helm --kube-context dps-l20-12 -n dps list
dpsctl server-version
dpsctl agent list
dpsctl topology list
```

项目环境导出 `DPS_KUBE_CONTEXT=dps-l20-12`、`DPS_KUBE_NODE=l20-12`，
并固定 dpsctl 的 CA、凭据和日志路径。旧容器节点创建入口与工具已退出交付目录，仅在迁移归档中保留。

安装与维护脚本不自动调用 `verification/scripts/`。前置准备脚本不安装 DPS；只有明确的 `install-dps.sh` 执行 Helm 安装。所有脚本均不调用 SDK 部署入口。

`kubernetes.sh stop` 只执行 `systemctl stop k3s`，现有 Pod/containerd 任务可能继续运行，不能将其当作停止全部 DPS 工作负载或功率控制的保证。凭据、kubeconfig 和私钥仅保存到权限 600 的专用文件，不输出到普通日志。

