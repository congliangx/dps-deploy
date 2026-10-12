# DPS 0.9 完整 Lab 手工安装步骤

本文是完整 Lab 的可重复首次安装流程：原生 K3s、4 rack BMC 模拟器、独立 PostgreSQL/OpenLDAP、DPS 与 PRS，使用原生命令，不混入故障排查实录。原 installstep 的全部历史已逐字保存到 [docs/operation-history.md](docs/operation-history.md)。步骤在远端 root 的 Bash 会话执行，适用于 Ubuntu 22.04/24.04 amd64 + systemd 单物理机。

先按根 [README 的组件选择表](README.md) 决定需要安装哪些部分。有真实 BMC 时跳过第 3 节；有可用 Kubernetes 时跳过第 2 节的初始化；复用 PostgreSQL / LDAP 时跳过对应服务部署和 Lab 身份生成，改用 [已有基础设施对接指南](dps-install/existing-infrastructure.md) 准备应用连接配置与 Secret。PRS / S3 按需求选择，不照搬本 Lab 的固定开关与资源数量。

下列命令使用本仓库完整 Lab 的配置和目录。企业现有集群不应直接 source Lab 环境后运行整段命令：先选自己的 kubeconfig/context 与 values，按对接指南逐项执行。已有服务不是“安装结束”，仍需核对 DPS 的数据库/目录权限、BMC 拓扑与密码、受信 CA、namespace 内 Secret 和 Helm 引用。

先在本机连接远端，登录后再进入自己的实际 clone 目录。下面 /raid/vince/deploy 仅为 L20-12 当前示例，可以不同；后续从该 Git 工作区自动推导源码位置，Lab 主机/运行目录从 deployment.yaml 读取；客户应用对接使用自己的 values 和 Secret。

## 0. Lab 统一参数、源码/运行目录和已有状态

在本机执行连接命令：

~~~bash
ssh root@L20-12
~~~

登录远端后执行下列命令，先将 cd 路径换成自己的实际 clone 目录；不要在默认 /root 下执行 git rev-parse。

~~~bash
bash
cd /raid/vince/deploy
set -euo pipefail
umask 077
DPS_SOURCE_ROOT=$(git rev-parse --show-toplevel)
# 空白 OS 先安装配置解析器依赖；已有可用版本可跳过。
apt-get update
apt-get install -y python3 python3-yaml
# Lab 脚本参数集中在此；客户已有服务另按对接指南准备自己的 Helm values。
cat deployment.yaml
source "$DPS_SOURCE_ROOT/dps-install/scripts/deployment-env.sh"
python3 - <<'PY'
import os
from pathlib import Path
source=Path(os.environ["DPS_SOURCE_ROOT"]).resolve()
runtime=Path(os.environ["DPS_RUNTIME_ROOT"]).resolve()
print("source:",source,"runtime:",runtime)
PY
mkdir -p "$DPS_RUNTIME_ROOT"
hostname
ip -4 address show dev "$DPS_INTERFACE"
df -h "$DPS_RUNTIME_ROOT"
docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || true
systemctl is-active k3s || true
ss -ltn
~~~

源码根从实际 clone 位置推导；runtime_root 由用户在 deployment.yaml 选择。可以填写绝对路径（如 /srv/dps-lab），也可以填写相对 deployment.yaml 所在目录的路径（如 .runtime）；填写 . 表示与源码同根。运行目录也可以在源码的上级目录。公开模板与生成配置使用不同文件，不因选择同根而覆盖模板，生成物始终由 .gitignore 排除。可选 CLI --runtime-root 的相对路径按执行目录解析。L20-12 当前的 /raid/vince/deploy 与 /raid/vince/deployed-test 是本实例布局，后续步骤只使用 DPS_SOURCE_ROOT/DPS_RUNTIME_ROOT，无需改其他文档的源码绝对路径。主机/网卡/命名/端口等也只改这一份配置。Compose project 读取 DPS_BMC_PROJECT、DPS_PG_PROJECT、DPS_LDAP_PROJECT。

检查 runtime 中已有 PGDATA、LDAP data.mdb、证书/密码、kubeconfig 与 Helm release。已有部署进入“维护”分支，保留原身份和数据库，跳过所有首次生成/初始化。不能复制本文直接覆盖 L20-12 的现有数据。Git 跟踪公开模板与配方；下载、生成配置、data、日志、报告、archive 进入所选 runtime_root，不提交 Git。改变 runtime_root 只是选择路径，不会自动迁移已有服务或数据库；已有实例须继续使用原目录，另行安排迁移时保留原身份与数据。

## 1. Lab 主机依赖、Helm/kubectl 与固定包下载

完整 Lab 逐项执行 [manual-prerequisites.md 第 1–4 节](dps-install/manual-prerequisites.md)：Docker 官方 apt 仓库 + Compose v2、curl/SHA 下载工具、NGC chart、11 个固定镜像、17 个 Debian .deb 和独立 LDAP 构建。

必要原生命令及预期结果：

~~~bash
docker version
docker compose version
helm version --short
kubectl version --client=true -o json
helm show chart "$DPS_RUNTIME_ROOT/dps-install/packages/dps-0.9.0.tgz"
docker image ls --digests
~~~

预期工具 Helm 3.22.0/kubectl 1.34.12，DPS chart 0.9.0 SHA 2fc7b6e098b17085bf9aaf010d86dfeaf62677fd0f80bb4c2702e91b0b3fd6ef，镜像 digest 与 artifact-sources.json 完全匹配，LDAP 2.6.10 从本次固定配方构建。下载或 cache 校验冲突时停在此步，不覆盖冲突包/已有镜像标签。

## 2. 可选：物理机原生 K3s 与 containerd 镜像

空白主机执行 [manual-prerequisites.md 第 5–6 节](dps-install/manual-prerequisites.md)：下载并校验固定 K3s binary/官方 installer/airgap images，显式写 k3s.yaml、systemd mount 依赖、kubeconfig/context，将 chart tags 从 Docker save 导入 K3s containerd。

已有 Kubernetes 发行版时复用其 kubeconfig/context、Ingress 和 StorageClass，跳过此处 K3s 服务初始化及 k3s ctr 命令；镜像由目标集群自己的镜像拉取/离线导入机制提供。确认目标 namespace/release/API/UI 不占用其他安装。

~~~bash
systemctl is-active k3s
kubectl --context "$DPS_KUBE_CONTEXT" get nodes -o wide
kubectl get storageclass
kubectl -n kube-system get deployment traefik
k3s ctr --namespace k8s.io images list
~~~

预期实际节点 l20-12（或配置中的小写 host_name）Ready、local-path/Traefik 就绪。没有 Docker Kubernetes 节点模拟。K3s containerd/kubelet/local-path 数据在 runtime/dps-install/data/kubernetes；维护时不要停止独立 Docker 服务。

## 3. 可选：4 rack / 72 GB300 BMC 模拟器

没有真实硬件且选择模拟时才执行 [hardware-sim/manual-install.md](hardware-sim/manual-install.md)：随机密码、BMC CA/72 外部 HTTPS leaf、公开 nodes/topology 渲染、GB300 synthetic config、nginx 72 Host 路由、固定镜像 Compose。

~~~bash
docker compose -p "$DPS_BMC_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/hardware-sim/runtime/compose.yaml" up -d --wait
docker exec "$DPS_PROXY_CONTAINER" nginx -t
curl -fSs --cacert "$DPS_RUNTIME_ROOT/dps-install/config/simulator-ca.crt" \
  "https://$DPS_HOST_IP:$DPS_BMC_START_PORT/readyz"
~~~

预期 4 rack×18 计算节点、72 唯一 URL；默认端口 18443–18514；每节点 4 GPU/2 CPU。模拟器不强制认证，私有 backend 自动证书与外部 strict CA 分开。必要凭据清单 runtime/dps-install/config/bmc-endpoints.csv 为 600，不入 Git。

## 4. 可选：独立 PostgreSQL 17.11 Lab 服务

没有可用数据库且选择本 Lab 服务时才执行 [manual-postgresql.md](dps-install/manual-postgresql.md)：独立 admin/dps 密码、PG CA/server SAN、限定 host/Pod/bridge HBA、首次初始化角色/四库/public 权限、Compose 持久化、verify-full 连接和备份。

~~~bash
docker compose -p "$DPS_PG_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/dps-install/config/postgresql/compose.yaml" up -d --wait
docker exec -u postgres "$DPS_PG_CONTAINER" psql -d postgres -Atc \
  "select datname,pg_get_userbyid(datdba) from pg_database where datname like 'dps%';"
~~~

预期 dps、dps_prs_config、dps_prs_config_staged、dps_prs_controller 均 Owner dps。应用非 superuser；严格 verify-full；不能启用 Core/Power Steering chart 的内建 PostgreSQL。已有 PGDATA 时不再运行 CREATE ROLE/CREATE DATABASE。

## 5. 可选：独立 OpenLDAP Lab 服务

没有可用目录且选择本 Lab 服务时才执行 [manual-ldap.md](dps-install/manual-ldap.md)：独立随机 admin/bind/user/noaccess 密码、SSHA、LDAPS CA/server/client cert、8 条 LDIF、groupOfNames、ACL、Compose、strict TLS bind/组查询与备份。

~~~bash
docker compose -p "$DPS_LDAP_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/dps-install/config/ldap/compose.yaml" up -d --wait
LDAPTLS_CACERT="$DPS_RUNTIME_ROOT/dps-install/config/ldap/tls/ca.crt" LDAPTLS_REQCERT=demand \
  ldapwhoami -x -H "ldaps://$DPS_HOST_IP:$DPS_LDAP_PORT" \
  -D "uid=dps-lab,ou=users,dc=dps,dc=lab" \
  -y "$DPS_RUNTIME_ROOT/dps-install/config/ldap/user.password"
~~~

预期真实用户 DN；dcpower-users member 包含 dps-lab，readonly bind 只读。DPS 0.9 Core 要求 CA/client cert/key；用户仍由密码认证。本次直接 LDAP，OIDC 关闭；不重放旧 permissive→LDAP JWT 迁移。

## 6. DPS 配置、证书与 Secret（本 Lab 为 13 个）

执行 [manual-install.md 第 1–4 节](dps-install/manual-install.md)：新 DPS CA/server/Agent/ingress、持续 JWT RSA、S3 keys、Controller LDAP JSON，原生 kubectl create secret --from-file，公开 values 模板渲染为 runtime values。

~~~bash
kubectl -n "$DPS_NAMESPACE" get secret
openssl verify -CAfile "$DPS_RUNTIME_ROOT/dps-install/config/tls/ca.crt" \
  -verify_hostname "$DPS_API_NAME" "$DPS_RUNTIME_ROOT/dps-install/config/tls/server.crt"
~~~

当前完整 Lab 预期 13 个 external Secret；客户配置按实际功能准备，不能用固定数量验收。password/database-password 均取 dps 应用密码；只读 LDAP bind 与 CA/client projected 挂载完整；两个内建 PG disabled、BMC strict TLS、Agent mTLS、Controller真实 LDAP/TLS、PRS两层 enabled。values 没有密码/私钥。

## 7. 手动 Helm 安装与真实 LDAP 登录

执行 [manual-install.md 第 5–6 节](dps-install/manual-install.md)：先原生清点 Ingress/Traefik 域名归属、lint/template，再安装。

~~~bash
helm upgrade --install "$DPS_RELEASE" "$DPS_RUNTIME_ROOT/dps-install/packages/dps-0.9.0.tgz" \
  --kube-context "$DPS_KUBE_CONTEXT" --namespace "$DPS_NAMESPACE" \
  --values "$DPS_RUNTIME_ROOT/dps-install/config/values.yaml" \
  --wait --timeout 20m --history-max 10
helm -n "$DPS_NAMESPACE" status "$DPS_RELEASE"
kubectl -n "$DPS_NAMESPACE" get pods,pvc
dpsctl --output json login --username dps-lab --password-stdin \
  < "$DPS_RUNTIME_ROOT/dps-install/config/ldap/user.password" \
  > "$DPS_RUNTIME_ROOT/verification/logs/dps-login.json"
jq '.status' "$DPS_RUNTIME_ROOT/verification/logs/dps-login.json"
dpsctl server-version
dpsctl agent list
~~~

当前完整 Lab 预期 deployed、9 工作负载 Ready、4 PVC Bound、0.9.0 客户端/服务端、LDAP admin 与 Agent connected。login JSON/CLI credential/token 均 600，不展示原文。外部访问 API/UI 需要 DNS/hosts 指向 host_ip，并信任 runtime/dps-install/config/tls/ca.crt。

## 8. 本 Lab 的电源类型/拓扑与可选 PRS 开关

完整 Lab 执行 [manual-install.md 第 7–8 节](dps-install/manual-install.md) 的原生命令：

~~~bash
dpsctl device upsert "$DPS_SOURCE_ROOT/dps-install/config/gb300-power-shelf-devices.yaml"
dpsctl topology validate "$DPS_RUNTIME_ROOT/dps-install/config/topology-4rack-dps09.json"
dpsctl topology import "$DPS_RUNTIME_ROOT/dps-install/config/topology-4rack-dps09.json"
dpsctl topology list
dpsctl settings update --set prs_enabled=true \
  --set prs_headroom_percent=-15 --set prs_scheduler_interval_seconds=5
dpsctl settings list
~~~

本 Lab 预期 110 实体、4 rack/72计算节点、inactive、72 条 AgentId 位于 Topology.Entities。用官方 GetTopologyModel 原始回读验证 AgentId；0.9 CLI export 省掉字段不能当作验证。缺少路由才执行 manual-install 中 current hash、forceUpdate=false 的官方 API update；禁止 CLI delete/reimport/force。

本 Lab 默认不激活拓扑、不创建资源组、不写 BMC 功率。PRS=true / headroom=-15% / scheduler=5 秒是本 Lab 的部署状态，客户按业务选择是否启用 PRS 及其参数。真实 BMC 使用自己的设备模型、拓扑和 AgentId 关系，不导入此处模拟节点蓝图；动态功率控制还需要后续单独验证。

## 9. 原生只读检查与安装后备份

~~~bash
kubectl get nodes -o wide
kubectl -n "$DPS_NAMESPACE" get pods,pvc
helm -n "$DPS_NAMESPACE" status "$DPS_RELEASE"
dpsctl agent list
dpsctl topology list
dpsctl settings list
~~~

按 PG/LDAP 手册重新备份到 runtime/dps-install/data 下，并校验 dump catalog/LDAP 条目。可选进一步验收放 [verification](verification/README.md)，结果只写 runtime/verification。宿主机/Agent Pod GET 与 Core→Agent 的 active-topology 派发分别报告；不把 inactive 的 INVALID_OPERATION/SERVER_NOT_STARTED 标为已通过 DPS 集成。

## 10. 已有实例维护分支

只读取同一 deployment.yaml 和已有 runtime values/identity/data，执行需要的 docker compose ps、kubectl/helm status、dpsctl 查询。更改明确的非秘密配置后，先 helm template 审阅再 upgrade。证书/密码/用户/JWT、PGDATA/LDAP data.mdb 与 PVC 不重新生成或删除。旧 LDAP 迁移、PRS 第一次启用、容器节点退役与路径迁移都在 operation-history 中，不是每日复现步骤。
