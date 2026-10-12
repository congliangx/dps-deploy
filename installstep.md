# DPS 0.9 完整 Lab 安装步骤（脚本与手工）

本文是完整 Lab 的可重复首次安装流程：原生 K3s、4 rack BMC 模拟器、独立 PostgreSQL/OpenLDAP、DPS 与 PRS，提供脚本入口和逐步原生命令两种方式，不混入故障排查实录。原 installstep 的全部历史已逐字保存到 [docs/operation-history.md](docs/operation-history.md)。步骤在远端 root 的 Bash 会话执行，适用于 Ubuntu 22.04/24.04 amd64 + systemd 单物理机。

先按根 [README 的组件选择表](README.md) 决定需要安装哪些部分。有真实 BMC 时跳过第 3 节；有可用 Kubernetes 时跳过第 2 节的初始化；复用 PostgreSQL / LDAP 时跳过对应服务部署和 Lab 身份生成，改用 [已有基础设施对接指南](dps-install/existing-infrastructure.md) 准备应用连接配置与 Secret。PRS / S3 按需求选择，不照搬本 Lab 的固定开关与资源数量。

下列命令使用本仓库完整 Lab 的配置和目录。企业现有集群不应直接 source Lab 环境后运行整段命令：先选自己的 kubeconfig/context 与 values，按对接指南逐项执行。已有服务不是“安装结束”，仍需核对 DPS 的数据库/目录权限、BMC 拓扑与密码、受信 CA、namespace 内 Secret 和 Helm 引用。

先在本机连接远端，登录后再进入自己的实际 clone 目录。下面 /raid/vince/deploy 仅为 L20-12 当前示例，可以不同；后续从该 Git 工作区自动推导源码位置，Lab 主机/运行目录从 deployment.yaml 读取；客户应用对接使用自己的 values 和 Secret。

## 0. 先选择路线，再准备会话和参数

### 0.1 所有 Lab 路线：连接、进入源码目录、确认配置

在本机执行连接命令：

~~~bash
ssh root@L20-12
~~~

登录后进入 Bash，将 cd 路径换成自己的实际 clone 目录；不要在默认 /root 下执行 git rev-parse：

~~~bash
bash
cd /raid/vince/deploy
set -euo pipefail
umask 077
DPS_SOURCE_ROOT=$(git rev-parse --show-toplevel)
cat "$DPS_SOURCE_ROOT/deployment.yaml"
~~~

先编辑 deployment.yaml，确认目标主机/IP、网卡、runtime_root、名称、端口和子网。首次新建使用没有已有身份或数据的运行位置；不要用当前 L20-12 实例配置重装这套已运行环境。源码根从实际 clone 推导，运行目录由用户选择：可以为绝对路径（如 /srv/dps-lab）、相对配置文件的路径（如 .runtime），或 . 表示与源码同根；也可以位于源码上级目录。公开模板与生成配置使用不同文件，生成物不提交 Git。CLI --runtime-root 的相对路径按执行目录解析。L20-12 当前源码/运行目录分别为 /raid/vince/deploy 和 /raid/vince/deployed-test，只是本实例的布局。

**新建整套 Lab：** 完成此小节并确认现状后，执行下面 A 或 B 的完整脚本即可；脚本自行安装缺少的解析器/主机依赖并读取配置，不要求先执行第 1–8 节。成功后加载 0.2 的环境，再到第 9 节检查。

**逐个组件安装或手工安装：** 继续完成 0.2，然后按第 1–8 节选择所需组件。每节的脚本路线与手工路线二选一，安装完成后才执行该节的检查。读取手册了解实现不等于还要执行一遍手册命令。

**已有实例维护：** 继续使用原配置、原 runtime 与身份，完成 0.2 的清点后到第 10 节；跳过新建身份/初始化。改变 runtime_root 只改变路径选择，不会迁移已有服务或数据库。

### 0.2 组件/手工路线及安装后检查：在同一 Bash 会话加载环境

下面只补齐配置解析依赖、加载统一变量并清点现状；不安装 BMC/PG/LDAP/Kubernetes/DPS。完整脚本成功后也使用此段加载检查命令所需变量；依赖已存在时不会重复 apt 安装：

~~~bash
# 沿用 0.1 的源码目录；新终端须先完成 0.1。
if ! python3 -c 'import yaml' >/dev/null 2>&1; then
  apt-get update
  apt-get install -y python3 python3-yaml
fi
source "$DPS_SOURCE_ROOT/dps-install/scripts/deployment-env.sh" \
  --config "$DPS_SOURCE_ROOT/deployment.yaml"
python3 - <<'PYENV'
import os
from pathlib import Path
source=Path(os.environ["DPS_SOURCE_ROOT"]).resolve()
runtime=Path(os.environ["DPS_RUNTIME_ROOT"]).resolve()
print("source:",source,"runtime:",runtime)
PYENV
mkdir -p "$DPS_RUNTIME_ROOT"
hostname
ip -4 address show dev "$DPS_INTERFACE"
df -h "$DPS_RUNTIME_ROOT"
docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || true
systemctl is-active k3s || true
ss -ltn
~~~

后文所有 DPS_*、KUBECONFIG、dpsctl 路径变量都来自这次加载；不能脱离此会话单独复制检查代码块。改动 deployment.yaml 后重新加载，再确认目标。Compose project 来自 DPS_BMC_PROJECT、DPS_PG_PROJECT、DPS_LDAP_PROJECT。

清点运行目录中的 PGDATA、LDAP data.mdb、证书/密码、kubeconfig、Helm release 和监听端口。存在已有部署时进入维护分支，保留原身份和数据库；不能删除状态文件绕过归属检查。Git 跟踪公开模板与配方；下载、生成配置、data、日志、报告和 archive 放入 runtime_root，不提交 Git。

## 整套脚本入口（与第 1–8 节逐组件安装二选一）

完成第 0.1 节后选择下面 A 或 B，或者完成第 0.2 节后按第 1–8 节逐个安装。A/B 完整脚本成功后已完成第 1–8 节的安装与 Lab 登记设置，下一步只需加载第 0.2 节环境并执行第 9 节检查/备份及可选 verification；不用再执行各节安装脚本或手册初始化命令。C 只覆盖第 7 节的 Helm 安装，其前置与后续须另外完成。若复用客户已有 BMC / PostgreSQL / LDAP 或任意企业 Kubernetes，请使用 [已有基础设施对接指南](dps-install/existing-infrastructure.md)；完整 Lab 脚本不会按组件选择跳过这些独立服务。

### A. 新建完整 Lab：一条脚本运行

先修改 deployment.yaml 为目标主机和本次实例的配置，确认运行目录、端口、Docker 子网、容器名称、namespace/release 和 API/UI 域名未占用。首次安装使用新的空运行目录；L20-12 当前配置对应已有实例，不用于新建测试实例。然后在源码目录执行：

~~~bash
bash dps-install/scripts/install-from-zero.sh \
  --config "$DPS_SOURCE_ROOT/deployment.yaml"
~~~

这是完整 Lab 安装：安装主机依赖/Docker、校验并下载固定包和镜像、生成新的 BMC/PG/LDAP/DPS 身份及配置、安装物理机原生 K3s、启动独立服务、应用 13 个 Lab Secret、导入镜像并安装 DPS，随后完成真实 LDAP 登录、设备/拓扑登记和 Lab PRS 参数设置。默认保留拓扑 inactive，不写 BMC 功率；生成物写到配置所选 runtime_root。具体动作和原生命令见 [前置](dps-install/manual-prerequisites.md)、[BMC](hardware-sim/manual-install.md)、[PostgreSQL](dps-install/manual-postgresql.md)、[LDAP](dps-install/manual-ldap.md) 和 [DPS](dps-install/manual-install.md) 手册。

也可以分阶段准备，最后再执行上面的完整命令：

~~~bash
# 校验/下载固定 chart、镜像和 LDAP 构建包，并构建本 Lab LDAP 镜像。
bash dps-install/scripts/install-from-zero.sh \
  --config "$DPS_SOURCE_ROOT/deployment.yaml" --download-only

# 在下载阶段之后生成 BMC、PG、LDAP、DPS 的密码、证书、配置和 Secret 文件。
bash dps-install/scripts/install-from-zero.sh \
  --config "$DPS_SOURCE_ROOT/deployment.yaml" --prepare-only
~~~

这两个模式都会先执行主机依赖脚本，可能安装 OS 软件包、Docker 和 Compose；下载阶段还会拉取/构建镜像并记录安装参数。prepare 阶段会写入新身份和配置。它们不会初始化/启动本 Lab 的 Kubernetes、BMC、PG、LDAP、DPS 服务，但不是只读 dry-run；不要用它们检查或覆盖已有非 bootstrap 实例。各阶段继续使用同一份配置和运行目录。

### B. 复用本机原生 K3s，安装一套新的完整 Lab

仅当本机已有可用的原生 K3s 时，可显式传入其外部管理员 kubeconfig，跳过 K3s 服务初始化。该入口仍通过本机 k3s ctr 导入镜像，仍依赖 Traefik CRD/Ingress 与合适的 StorageClass；管理员 kubeconfig 必须指向这台物理机的集群，当前 context 必须正确，并具备 namespace、Secret、Ingress 和 Helm 安装权限。这不是复用任意远程企业集群的通用入口。

先读取外部 kubeconfig 的 current-context，并将 deployment.yaml 的 kube_context 设置成该相同名称，确保安装后第 0.2 节重新加载的环境与实际集群一致。再在配置中选择独立的新 namespace/release、instance_prefix、Compose project、AgentId、API/UI 域名、端口、子网和空运行目录，核对不会占用现有实例，再执行：

~~~bash
# 替换为现有管理员 kubeconfig 的真实路径；不能填写本次 runtime 内的目标副本。
DPS_ADMIN_KUBECONFIG=/path/to/existing-admin-kubeconfig.yaml
kubectl --kubeconfig "$DPS_ADMIN_KUBECONFIG" config current-context
kubectl --kubeconfig "$DPS_ADMIN_KUBECONFIG" get nodes,storageclass
kubectl --kubeconfig "$DPS_ADMIN_KUBECONFIG" -n kube-system get deployment traefik
bash dps-install/scripts/install-from-zero.sh \
  --config "$DPS_SOURCE_ROOT/deployment.yaml" \
  --kubeconfig "$DPS_ADMIN_KUBECONFIG"
~~~

该模式复制外部 kubeconfig 到本次运行目录，使用其 current-context；BMC 模拟器、独立 PostgreSQL/OpenLDAP、Lab 身份/Secret、DPS 和 PRS 仍由完整脚本新建。需要复用这些其他服务时，改走对接指南和原生 Helm 流程。

### C. 前置条件、配置和 Secret 已准备好：仅安装/升级 Lab DPS

完成第 0.2 节环境加载后，如果第 1–6 节已完成，或同一 Lab 实例已有可用的原生 K3s、独立 PG/LDAP/BMC、固定 chart/镜像、values、证书和 namespace 内 Secret，可直接运行（与第 7 节脚本是同一入口，只执行一次）：

~~~bash
bash dps-install/scripts/install-dps.sh \
  --config "$DPS_SOURCE_ROOT/deployment.yaml"
~~~

此入口检查本机原生 K3s 和目标节点、chart 校验值、Lab LDAP/外部数据库及 PRS/TLS 配置，然后执行 Helm 安装/升级。它不创建基础服务，不生成或应用 Secret，也不完成登录、拓扑登记或 PRS 设置；新实例还需按 [DPS 手册](dps-install/manual-install.md) 完成对应后续步骤。它针对本仓库的 Lab values 约束，客户自有认证、数据库或集群组合按对接指南执行原生 Helm 命令。

## 逐组件路线的执行规则

以下第 1–8 节用于按需安装。每节先说明前置条件，再选“脚本安装”或“手工安装”，最后执行标为“安装后检查”的代码块。手工路线是跳到链接手册完整执行所指章节；下方检查是验收该阶段，不要求先手工安装后再执行同一组件脚本。已做完的启动、Secret apply、Helm、登录、拓扑导入或设置更新均不再重复。

独立 BMC/PG/LDAP 脚本只新建自己的 Lab 组件。**不要在这些组件已初始化后接续 A/B 的整套 install-from-zero.sh**：完整入口要求自己的统一 bootstrap 状态，会拒绝接管这样已有的数据/身份。需要继续安装 DPS 时，保持同一配置和原身份，补齐所缺第 1/2 节，再按第 6 节准备/应用 Secret 与 values、第 7 节的 DPS-only 或手工 Helm，以及第 8 节的登记设置继续。若希望整套一条脚本完成，应从一开始选择 A/B。

## 1. Lab 主机依赖、Helm/kubectl 与固定包下载

**安装入口（二选一）：**

- 脚本路线：先执行下面的主机依赖脚本。只安装独立 BMC/PG/LDAP 时，此步完成后直接到对应第 3/4/5 节，各组件入口只下载自己需要的固定材料；无需先下载完整 Lab 的 chart/全部镜像，也无需 Helm/Kubernetes。
- 手工路线：按 [manual-prerequisites.md 的执行准备及第 1 节](dps-install/manual-prerequisites.md) 安装 OS/Docker/Compose，按实际需要继续其第 2–4 节的工具/包/LDAP 构建。完整 Lab 执行全部；已有符合要求的工具先检查并复用，不重复安装。

~~~bash
bash dps-install/scripts/install-host-dependencies.sh
~~~

逐组件搭建完整 Lab 还需下面两条，下载/校验完整固定包并构建 LDAP 镜像，然后安装固定 Helm/kubectl。它们不安装业务服务；工具安装器不会覆盖无归属的系统二进制，已有可用工具按手册复用：

~~~bash
python3 dps-install/scripts/download-artifacts.py \
  --config "$DPS_SOURCE_ROOT/deployment.yaml" --component all
python3 dps-install/scripts/install-tools.py \
  --config "$DPS_SOURCE_ROOT/deployment.yaml"
~~~

客户复用已有基础设施时只准备实际启用组件的工具/镜像，不必下载完整 Lab 清单，按 [对接指南](dps-install/existing-infrastructure.md) 执行。

**主机依赖安装后检查（仅安装 BMC/PG/LDAP 也可执行）：**

~~~bash
docker version
docker compose version
~~~

**完整 Lab 工具/包准备后检查（仅在已执行下载与工具安装后运行）：**

~~~bash
helm version --short
kubectl version --client=true -o json
helm show chart "$DPS_RUNTIME_ROOT/dps-install/packages/dps-0.9.0.tgz"
docker image ls --digests
~~~

只安装独立组件时跳过第二个检查块，直接到第 3/4/5 节。完整 Lab 预期 Helm 3.22.0/kubectl 1.34.12、DPS chart 0.9.0，chart SHA 为 2fc7b6e098b17085bf9aaf010d86dfeaf62677fd0f80bb4c2702e91b0b3fd6ef；镜像 digest 与 artifact-sources.json 匹配。LDAP 2.6.10 来自固定配方。发现缓存校验冲突时停在此步，保留原包/镜像排查。

## 2. 可选：物理机原生 K3s 与 containerd 镜像

仅在缺少 Kubernetes 且选择本 Lab 原生 K3s 时安装。第 1 节的 Docker、下载工具和 kubectl/Helm 应已可用；第 0.2 节已加载环境。

**安装入口（二选一）：**

- 脚本路线：在没有其他 K3s 安装的空白主机执行下面三条；依次安装/启动物理机原生 K3s、将 Core/Agent/UI 镜像导入其 containerd、再导入 PRS 相关镜像。K3s 脚本校验固定包、配置 systemd 和运行目录、生成 kubeconfig 并等待节点 Ready；不会安装 DPS。
- 手工路线：按 [manual-prerequisites.md 第 5–6 节](dps-install/manual-prerequisites.md) 完成 K3s、kubeconfig/context 和镜像导入，完成后直接运行本节检查。

~~~bash
bash dps-install/scripts/install-kubernetes.sh \
  --config "$DPS_SOURCE_ROOT/deployment.yaml"
python3 dps-install/scripts/stage-runtime-images.py \
  --config "$DPS_SOURCE_ROOT/deployment.yaml"
python3 dps-install/scripts/stage-prs-images.py \
  --config "$DPS_SOURCE_ROOT/deployment.yaml"
~~~

已有 Kubernetes 时跳过上面的安装与 k3s ctr 导入，使用自己的 kubeconfig/context、Ingress、StorageClass 和镜像提供机制。已有 K3s 也先核对其归属，不能通过新运行目录接管其他安装。任意客户集群按对接指南执行；整套脚本 B 的复用范围仅为本机原生 K3s。

**安装后检查（本 Lab K3s；只查询状态）：**

~~~bash
systemctl is-active k3s
kubectl --context "$DPS_KUBE_CONTEXT" get nodes -o wide
kubectl --context "$DPS_KUBE_CONTEXT" get storageclass
kubectl --context "$DPS_KUBE_CONTEXT" -n kube-system get deployment traefik
k3s ctr --namespace k8s.io images list
~~~

预期配置中的实际物理节点 Ready、local-path/Traefik 就绪。K3s containerd/kubelet/local-path 数据在 runtime/dps-install/data/kubernetes；维护时不要停止独立 Docker 服务。

## 3. 可选：4 rack / 72 GB300 BMC 模拟器

有真实 BMC 时跳过本节，直接使用真实 URL/密码/CA 和设备拓扑。没有硬件且选择模拟时，先完成第 0.2 节与第 1 节的主机依赖；独立脚本负责本组件的固定镜像、配置生成和启动。

**安装入口（二选一）：**

- 脚本路线：首次新建此 Lab BMC 模拟器执行下面一条；会生成随机密码、BMC CA 与 72 个外部 HTTPS 入口共用的 leaf、nodes/topology、GB300 synthetic config、nginx 路由及 Compose，并启动本组件。它不安装 PostgreSQL/LDAP/Kubernetes/DPS。
- 手工路线：按 [hardware-sim/manual-install.md](hardware-sim/manual-install.md) 从执行准备开始，完整执行配置/证书生成、镜像、Compose 启动和该手册检查。完成后本节只做检查，**不用再执行一次 docker compose up**。

~~~bash
bash hardware-sim/scripts/install-bmc.sh \
  --config "$DPS_SOURCE_ROOT/deployment.yaml"
~~~

具体生成步骤、产物与维护方式见上述手册；prepare-bmc-fresh.py 只生成输入，单独执行它不等于完成安装。维护已有实例使用既有身份与 Compose；不要重新做 fresh 初始化。

**安装后检查（启动已由所选路线完成；下面不再启动容器）：**

~~~bash
docker compose -p "$DPS_BMC_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/hardware-sim/runtime/compose.yaml" ps
docker exec "$DPS_PROXY_CONTAINER" nginx -t
curl -fSs --cacert "$DPS_RUNTIME_ROOT/dps-install/config/simulator-ca.crt" \
  "https://$DPS_HOST_IP:$DPS_BMC_START_PORT/readyz"
~~~

预期 4 rack×18 计算节点、72 唯一 URL；默认端口 18443–18514，每节点 4 GPU/2 CPU。模拟器不强制认证，私有 backend 自动证书与外部 strict CA 分开。DPS 对接用私密 runtime/dps-install/config/bmc-endpoints.csv 和 simulator-ca.crt；凭据清单为 600，不入 Git。

## 4. 可选：独立 PostgreSQL 17.11 Lab 服务

已有可用数据库时跳过服务新建，按对接指南准备 DPS 所需库/权限、真实密码、CA 和 namespace Secret。选择独立 Lab PG 时先完成第 0.2 节与第 1 节的主机依赖；不要求先安装 BMC、LDAP 或 Kubernetes。

**安装入口（二选一）：**

- 脚本路线：首次新建此 Lab 数据库执行下面一条；准备固定镜像、随机 admin/dps 密码、PG CA/server SAN、HBA/TLS/SCRAM、四库初始化输入和 Compose，启动独立 PostgreSQL 并等待健康。它不部署其他组件；生成的 Secret YAML 尚未应用到 Kubernetes。
- 手工路线：按 [manual-postgresql.md](dps-install/manual-postgresql.md) 完整执行凭据/证书、初始化 SQL、Compose 启动及严格 TLS 连接检查。完成后本节只做检查，**不用再执行一次 docker compose up**。手册的备份是安装后的独立动作，见第 9 节。

~~~bash
bash dps-install/scripts/install-postgresql.sh \
  --config "$DPS_SOURCE_ROOT/deployment.yaml"
~~~

首次建库由 PostgreSQL 官方镜像在空 PGDATA 初始化时执行；已有 PGDATA 不重跑 CREATE ROLE/CREATE DATABASE。prepare-postgresql.py 只生成输入，不启动数据库，不可当作一键安装。密码、CA 和初始化产物的位置及内容见手册。

**安装后检查（查询现有容器和库归属）：**

~~~bash
docker compose -p "$DPS_PG_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/dps-install/config/postgresql/compose.yaml" ps
docker exec -u postgres "$DPS_PG_CONTAINER" psql -d postgres -Atc \
  "select datname,pg_get_userbyid(datdba) from pg_database where datname like 'dps%';"
~~~

完整 Lab 预期 dps、dps_prs_config、dps_prs_config_staged、dps_prs_controller 均 Owner dps；应用非 superuser，严格 verify-full，不启用 Core/Power Steering chart 的内建 PostgreSQL。库数量取决于是否启 PRS，客户配置不以本 Lab 固定四库验收。

## 5. 可选：独立 OpenLDAP Lab 服务

已有 LDAP/IdP 时跳过服务新建，复用真实目录身份与信任链并按对接指南配置认证。选择独立 Lab LDAP 时先完成第 0.2 节与第 1 节的主机依赖；不要求先安装 BMC、PG 或 Kubernetes。

**安装入口（二选一）：**

- 脚本路线：首次新建此 Lab 目录执行下面一条；下载固定 Debian 包并构建 OpenLDAP 镜像，生成随机 admin/bind/user/noaccess 密码、SSHA、LDAPS CA/server/client cert、LDIF/组/ACL 和 Compose，启动独立目录并等待健康。它不安装其他组件，也不会把 DPS 切换为 LDAP 或应用 Secret。
- 手工路线：先按 [manual-prerequisites.md 第 4 节](dps-install/manual-prerequisites.md) 构建镜像，再按 [manual-ldap.md](dps-install/manual-ldap.md) 完整执行身份/证书、LDIF、Compose 启动及严格 TLS bind/组查询。完成后本节只做检查，**不用再执行一次 docker compose up**。备份见第 9 节。

~~~bash
bash dps-install/scripts/install-ldap.sh \
  --config "$DPS_SOURCE_ROOT/deployment.yaml"
~~~

新目录条目只在空 LDAP 数据目录首次初始化时导入；已有 data.mdb 不重新导入或轮换密码。prepare-ldap-fresh.py 只生成输入，单独执行它不等于完成安装。DPS 所需 CA/client cert/key、只读 bind 和 Secret 输入见手册。

**安装后检查（查询容器状态和严格 TLS 用户 bind）：**

~~~bash
docker compose -p "$DPS_LDAP_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/dps-install/config/ldap/compose.yaml" ps
LDAPTLS_CACERT="$DPS_RUNTIME_ROOT/dps-install/config/ldap/tls/ca.crt" LDAPTLS_REQCERT=demand \
  ldapwhoami -x -H "ldaps://$DPS_HOST_IP:$DPS_LDAP_PORT" \
  -D "uid=dps-lab,ou=users,dc=dps,dc=lab" \
  -y "$DPS_RUNTIME_ROOT/dps-install/config/ldap/user.password"
~~~

预期真实用户 DN，dcpower-users 组包含 dps-lab，readonly bind 只读。DPS 0.9 Core 要求 CA/client cert/key；用户仍通过密码认证。本 Lab 使用 LDAP，OIDC 关闭。

## 6. DPS 配置、证书与 Secret

在 Kubernetes、PG、LDAP 和 BMC 输入均就绪后执行。本 Lab 为 13 个外部 Secret；客户按实际功能供给，不以固定数量验收。

**准备与应用入口：**

- 整套 A/B 已完成本节：生成 DPS/Agent/Ingress TLS、持久 JWT、S3/Controller 输入与 values，创建归属 namespace，并应用本 Lab Secret。直接执行本节检查。
- 逐组件路线：沿用第 3–5 节已经生成的真实密码、CA/客户端证书和 Secret YAML；先按 [对接指南的 Secret/连接配置说明](dps-install/existing-infrastructure.md) 核对目标 namespace、Secret 名称/key 与实际连接参数。只为尚未具备的 DPS 自身 TLS/JWT/S3 身份执行 [manual-install.md 第 1–2 节](dps-install/manual-install.md)，已有对应身份则保留并跳过生成；再按该手册第 3–4 节核对/应用已有 Secret YAML，并渲染 values。不要重新运行 PG/LDAP/BMC 手册的身份生成。这里仍需明确执行所缺 openssl、namespace/Secret apply 和 values 准备；尚不执行手册第 5–8 节的 Helm/登录/登记。

逐组件路线进入 DPS 手册前，在当前 Bash 会话设置其章节共用变量；这是会话/输出目录准备，不生成身份或应用 Secret：

~~~bash
config="$DPS_RUNTIME_ROOT/dps-install/config"
tls="$config/tls"
mkdir -p "$DPS_RUNTIME_ROOT/verification/logs"
~~~

独立 PG/LDAP/BMC 入口会保存 Secret 文件，但不会在集群创建它们；本节把同一真实凭据和信任材料供给目标 namespace。已有服务密码/CA 不重新随机生成，已有 Secret 仅核对或按实际配置应用。prepare-dps-fresh.py 只生成输入，既不创建 namespace/应用 Secret，也不安装 Helm；已经运行过该生产者的实例保留其身份，不能再执行手册的首次生成段落。

**准备后检查（不创建或应用 Secret）：**

~~~bash
kubectl --context "$DPS_KUBE_CONTEXT" -n "$DPS_NAMESPACE" get secret
openssl verify -CAfile "$DPS_RUNTIME_ROOT/dps-install/config/tls/ca.crt" \
  -verify_hostname "$DPS_API_NAME" "$DPS_RUNTIME_ROOT/dps-install/config/tls/server.crt"
~~~

完整 Lab 的 password/database-password 使用同一 dps 应用密码，LDAP bind 与 CA/client 挂载就绪，内建 PG disabled，BMC strict TLS、Agent mTLS、Controller LDAP/TLS 和 PRS 两层配置匹配。values 不存放密码或私钥。

## 7. Helm 安装 DPS，再准备 dpsctl 登录

第 1–6 节所选前置服务、chart/镜像、values、namespace/Secret 都应就绪。整套 A/B 已完成 Helm 与登录，直接到检查；C 与本节脚本是同一入口，只执行一次。

**Helm 安装入口（二选一）：**

- 脚本路线：执行下面一条，仅检查并安装/升级 Lab DPS；脚本不会生成/apply Secret，不安装基础服务，也不登录或登记拓扑。
- 手工路线：按 [manual-install.md 第 5 节](dps-install/manual-install.md) 完整执行域名归属检查、lint/template 和 Helm 安装，完成后跳过下面同一 Helm 脚本。

~~~bash
bash dps-install/scripts/install-dps.sh \
  --config "$DPS_SOURCE_ROOT/deployment.yaml"
~~~

**Helm 完成后的下一步：** 两条逐组件 Helm 路线都继续 [manual-install.md 第 6 节](dps-install/manual-install.md)，安装匹配 dpsctl、确认 API/UI DNS/hosts、通过真实 LDAP 登录并保存私密 credential。该小节不重新安装 Helm，也不重新生成身份。整套 A/B 已做这些动作，不重复登录初始化。

**安装并登录后检查（不执行 Helm、login 或配置写入）：**

~~~bash
helm --kube-context "$DPS_KUBE_CONTEXT" -n "$DPS_NAMESPACE" status "$DPS_RELEASE"
kubectl --context "$DPS_KUBE_CONTEXT" -n "$DPS_NAMESPACE" get pods,pvc
dpsctl --version
dpsctl server-version
dpsctl agent list
~~~

本 Lab 预期 release deployed、9 个工作负载 Ready、4 PVC Bound、客户端/服务端 0.9.0、Agent connected。CLI credential/token/login JSON 保持 600，不展示原文。API/UI 访问需正确 DNS/hosts 并信任 runtime/dps-install/config/tls/ca.crt。

## 8. 登记本 Lab 电源类型/拓扑，再选择 PRS 设置

这是安装后的 DPS 配置写入阶段，包含 device upsert、拓扑首次 import/必要关系更新和 settings update；不是只读健康检查。需先完成第 7 节登录。

**配置入口：**

- 整套 A/B 已登记模拟电源、导入 inactive 四 rack 拓扑并设置 Lab PRS=true/-15%/5 秒，不重跑 import 或开关设置。
- 逐组件 Lab 路线：先按 [manual-install.md 第 7 节](dps-install/manual-install.md) 登记、验证、首次导入并通过官方 GetTopologyModel 回读 AgentId；再按该手册第 8 节明确设置所需 PRS 开关。只执行尚未完成的动作；已有同名拓扑不再次 import，不删除重建。
- 真实 BMC/客户环境：使用自己的设备模型、拓扑和 AgentId，按对接指南选择 PRS；跳过本 Lab 模拟蓝图和固定参数。

**配置后检查（仅查询）：**

~~~bash
dpsctl device list
dpsctl topology list
dpsctl settings list
dpsctl resource-group list
~~~

本 Lab 预期 110 实体、4 rack/72 计算节点、inactive，官方原始回读包含 72 条 Topology.Entities 的 AgentId。0.9 CLI export 会省略 AgentId，不能单靠其结果验收。缺少路由时按手册 current hash、forceUpdate=false 的 API 更新流程执行；不是默认再更新一次。

本 Lab 不激活拓扑、不创建资源组、不写 BMC 功率。PRS=true / headroom=-15% / scheduler=5 秒是 Lab 选择；动态功率控制需要后续独立授权和验证。

## 9. 安装完成：只读检查、备份与可选验证

整套 A/B 成功后直接到此处；逐组件/手工路线完成所选第 1–8 节后也到此处。先确认第 0.2 节环境已经加载，并具备第 7 节登录 credential。

**只读检查（可直接执行，不再启动容器或安装 Helm）：**

~~~bash
kubectl --context "$DPS_KUBE_CONTEXT" get nodes -o wide
kubectl --context "$DPS_KUBE_CONTEXT" -n "$DPS_NAMESPACE" get pods,pvc
helm --kube-context "$DPS_KUBE_CONTEXT" -n "$DPS_NAMESPACE" status "$DPS_RELEASE"
dpsctl agent list
dpsctl topology list
dpsctl settings list
~~~

**备份（单独的安装后动作，会写备份文件）：** 按 [PG 手册](dps-install/manual-postgresql.md) 与 [LDAP 手册](dps-install/manual-ldap.md) 的备份小节执行一次并核对 dump catalog/LDAP 条目；无需为备份重跑它们的初始化或启动章节。备份进入 runtime/dps-install/data，日志/报告进入 runtime/verification。

**进一步验证（按需选择）：** 见 [verification/README.md](verification/README.md)；整套安装脚本不会自动执行这些验收，验收报告也不是安装依赖。宿主机/Agent Pod 的 BMC GET 与 Core→Agent active-topology 派发分别报告；inactive 返回 INVALID_OPERATION/SERVER_NOT_STARTED 不代表 DPS 集成已通过。

## 10. 已有实例维护：使用既有身份和数据

先完成第 0.1–0.2 节，确认同一配置、runtime、context 和 release；不用再执行第 1–8 节的新建流程。容器状态用对应 compose ps，Kubernetes/Helm/dpsctl 查询可直接沿用第 9 节，只运行与本实例实际启用组件相符的检查。

需要启停已有独立服务时使用 [BMC 维护说明](hardware-sim/manual-install.md)、[PG 手册](dps-install/manual-postgresql.md)、[LDAP 手册](dps-install/manual-ldap.md) 对应维护命令；启停属于明确服务动作，不是检查。更改非秘密配置后先人工审阅 values 和 helm template，再执行明确的 Helm upgrade。

保留原证书/密码/用户/JWT、PGDATA/LDAP data.mdb 与 PVC，不重新生成或删除。旧 LDAP 迁移、PRS 第一次启用、容器节点退役与路径迁移记录在 [operation-history](docs/operation-history.md)，不属于日常安装/维护命令。
