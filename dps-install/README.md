# DPS 0.9 安装与基础设施对接

## 安装完成后：访问与日常维护

**安装后继续阅读 [dps-access.md](dps-access.md)：加载环境、访问 Kubernetes/Helm、登录 DPS CLI、配置浏览器域名与 CA，以及查询日志、备份和服务启停。** 每次新的 SSH/Bash 会话需重新加载环境；维护保留现有身份与数据。

## 安装前先选路线

按根 [组件选择表](../README.md) 和 [前置要求](manual-prerequisites.md) 确认范围。已有 Kubernetes、数据库、LDAP 和真实 BMC 的客户从 [对接指南](existing-infrastructure.md) 开始，准备自己的 values、权限、证书和 Secret 后使用 Helm。

本页是完整 Lab 的分步导航。需要整套脚本或分阶段入口时，使用 [installstep.md](../installstep.md)；只新建缺少部分时，选择下面的组件脚本或手册，不重复执行两条路线。Lab 的容器名、固定版本、13 Secret、9 工作负载和 4 PVC 均是本组合的配置。

## 配置与环境

[deployment.yaml](../deployment.yaml) 设置 Lab 脚本参数；客户的应用连接与认证配置写入自己的 Helm values。以下 Lab 命令在 root Bash、源码根执行，先加载环境：

~~~bash
# 先进入实际 clone 的仓库根目录。
DPS_SOURCE_ROOT=$(git rev-parse --show-toplevel)
source "$DPS_SOURCE_ROOT/dps-install/scripts/deployment-env.sh"
~~~

生成输入在 $DPS_RUNTIME_ROOT/dps-install/config，下载包在 dps-install/packages，数据库/K3s/备份在 dps-install/data。runtime_root 可同根、位于仓库内或外部，相对配置文件目录解析；布局与 Git 边界见 [根 README](../README.md)。

## 1. 下载与物理集群

按 [主机/K3s 手册](manual-prerequisites.md) 安装或复用物理集群，下载固定 chart、镜像和工具。完整 Lab 的 OpenLDAP 镜像由固定 base 与 Debian 包构建。

**安装后只读检查：**

~~~bash
helm show chart "$DPS_RUNTIME_ROOT/dps-install/packages/dps-0.9.0.tgz"
docker image ls --digests
systemctl is-active k3s
kubectl --context "$DPS_KUBE_CONTEXT" get nodes -o wide
kubectl get storageclass
~~~

预期节点 Ready、StorageClass 可用。固定版本及 SHA 在前置手册和 artifact-sources.json，不使用容器模拟 Kubernetes 节点。

## 2. 可选：独立 PostgreSQL 与 OpenLDAP

先完成 installstep 第 0–1 节的参数与主机依赖，只安装缺少的服务。

**脚本安装：** 各入口完成对应组件的下载/构建、身份/证书/配置与 Secret YAML、Compose 启动及基本自检；无需先执行手册生成配置。

~~~bash
# 只运行需要新建的服务；已有服务直接对接。
bash dps-install/scripts/install-postgresql.sh --config "$DPS_SOURCE_ROOT/deployment.yaml"
bash dps-install/scripts/install-ldap.sh --config "$DPS_SOURCE_ROOT/deployment.yaml"
~~~

**手工安装：** 改为完整执行 [PG 第 1–4 节](manual-postgresql.md) 或 [LDAP 第 1–4 节](manual-ldap.md)。LDAP 先构建固定镜像；两份手册第 4 节已启动服务。

**安装后只读检查：** 只运行本机已安装的 Lab 服务对应代码块；客户远端服务按对接指南检查实际地址。

PostgreSQL：

~~~bash
docker compose -p "$DPS_PG_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/dps-install/config/postgresql/compose.yaml" ps
docker exec -u postgres "$DPS_PG_CONTAINER" psql -d postgres -Atc \
  "select datname,pg_get_userbyid(datdba) from pg_database where datname like 'dps%';"
~~~

LDAP：

~~~bash
docker compose -p "$DPS_LDAP_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/dps-install/config/ldap/compose.yaml" ps
LDAPTLS_CACERT="$DPS_RUNTIME_ROOT/dps-install/config/ldap/tls/ca.crt" LDAPTLS_REQCERT=demand \
  ldapwhoami -x -H "ldaps://$DPS_HOST_IP:$DPS_LDAP_PORT" \
  -D "uid=dps-lab,ou=users,dc=dps,dc=lab" \
  -y "$DPS_RUNTIME_ROOT/dps-install/config/ldap/user.password"
~~~

组件脚本只生成 Secret 文件；后续为 DPS 创建或引用 namespace Secret。保留已生成的密码和 CA，按分步流程继续，不接续整套 install-from-zero 初始化。Lab PG 使用非 superuser 应用角色、四库、TLS/SCRAM；LDAP 使用真实用户/组、只读 bind 和 LDAPS，详细预期在各手册。

需要模拟硬件时，按 [BMC 安装入口](../hardware-sim/README.md) 选择脚本或手工路线；真实 BMC 直接按对接指南接入。

## 3. 必需：Secret、values 与 Helm

按 [DPS 手册第 1–5 节](manual-install.md) 准备 DPS 身份、namespace Secret、values 并执行 Helm。已由组件脚本生成的 PG/LDAP/BMC 身份继续使用，跳过对应初次密码生成。复用客户服务时，按 [对接指南](existing-infrastructure.md) 使用其真实凭据和证书；密码不入 values、argv 或日志。

本机原生 K3s 的 Lab values、证书和 Secret 已就绪时，可用以下脚本替代手册第 5 节的 Helm 安装动作：

~~~bash
bash dps-install/scripts/install-dps.sh --config "$DPS_SOURCE_ROOT/deployment.yaml"
~~~

此入口只安装/升级 DPS，不准备前置服务、身份和 Secret，也不完成后续登录/拓扑/PRS 参数设置。客户自选基础设施继续使用对接指南的 Helm 命令。安装前检查 API/UI 路由归属，避免占用其他实例域名。

**安装后只读检查：**

~~~bash
kubectl -n "$DPS_NAMESPACE" get secret
helm --kube-context "$DPS_KUBE_CONTEXT" -n "$DPS_NAMESPACE" status "$DPS_RELEASE"
kubectl -n "$DPS_NAMESPACE" get pods,pvc
~~~

完整 Lab 预期 release deployed、9 工作负载 Ready、4 PVC Bound；启用不同组件时按实际配置检查。Helm 渲染通过与运行验收分别记录。

## 4. 登录、拓扑与可选 PRS

完整 Lab 脚本已完成登录、设备登记、inactive 拓扑导入和 PRS 参数设置。分组件/手工路线按 [DPS 第 6–8 节](manual-install.md) 完成 CLI、DNS/CA、LDAP 登录及设备/拓扑/PRS 配置；已完成的动作不重复执行。

**完成登录和登记后只读检查：**

~~~bash
dpsctl server-version
dpsctl agent list
dpsctl topology list
dpsctl settings list
~~~

Lab 预期 LDAP admin、Agent connected、4 rack/72 计算节点、inactive、PRS=true。AgentId 用官方 GetTopologyModel 回读；CLI 导出字段与更新限制见手册。

真实 BMC 使用实际设备模型、拓扑和凭据；PRS 按业务需求选择。当前 Lab 不激活拓扑、不建资源组、不写 BMC 功率，未验收动态功率闭环。

## 后续维护与验证

访问材料在 $DPS_RUNTIME_ROOT/dps-install/config，账号为 dps-access.json，CLI 会话为 dpsctl/credentials.yaml，CA 为 tls/ca.crt；生成阶段、权限与访问步骤见 [dps-access.md](dps-access.md)。

按实际安装范围执行 [验证](../verification/README.md)，维护工具见 [脚本索引](scripts/README.md)。验证报告不作为安装输入。已有实例跳过初次创建，保留身份/data；带日期的 LDAP/PRS 变更与验收见 [操作历史](../docs/operation-history.md)。
