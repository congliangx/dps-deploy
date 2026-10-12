# DPS 0.9 安装入口与基础设施对接

先读根 [README 的组件选择表](../README.md)，按已有基础设施选择安装范围。已有 Kubernetes、数据库、LDAP 和真实 BMC 的客户从 [已有基础设施对接指南](existing-infrastructure.md) 开始，只准备 DPS 的 values、权限、证书与 Secret 后执行 Helm，无需安装 K3s、模拟器或另一套数据库/目录服务。

安装前阅读 [前置要求与手工安装](manual-prerequisites.md)：准备项、组件复用选择、版本说明、安装命令和状态检查集中在同一页。已有服务的应用对接按上面的指南准备，只执行缺少组件的相应步骤。

本页后续命令是完整 Lab 示例：配置和下载→独立 PG/LDAP→13 Secret→values/Helm→真实 LDAP 登录→inactive 模拟拓扑/PRS。完整顺序在根 [installstep.md](../installstep.md)，原生命令的长步骤分别在 [主机/K3s](manual-prerequisites.md)、[PG](manual-postgresql.md)、[LDAP](manual-ldap.md)、[DPS](manual-install.md)。只新装缺少的组件即可；以下 Docker 容器名、目录、账号、Secret/Pod/PVC 数量均属于该 Lab 配置。

## 路径与配置

[deployment.yaml](../deployment.yaml) 统一设置本仓库 Lab 脚本参数；它不是任意客户环境的 DPS Helm values。客户对接信息应写入自己的 values，并使用目标集群的 kubeconfig/context。下列 source 命令只用于本仓库 Lab：

~~~bash
# 先进入实际 clone 的仓库根目录。
DPS_SOURCE_ROOT=$(git rev-parse --show-toplevel)
source "$DPS_SOURCE_ROOT/dps-install/scripts/deployment-env.sh"
~~~

Git 跟踪 dps-install 的公开 config 模板、artifact-sources.json、LDAP 构建配方与脚本。运行时输入是 $DPS_RUNTIME_ROOT/dps-install/config；下载包是 runtime/dps-install/packages；数据库、K3s、备份是 runtime/dps-install/data。runtime_root由用户选择：.runtime为仓库内专用子目录，.为源码与运行材料同根，/srv/dps-lab为自选绝对目录，源码上级目录也可用。配置中的相对路径按deployment.yaml所在目录解析；live values/真实 Secret、密码、证书/私钥和 kubeconfig 均排除 Git。

## 1. Lab 示例：下载与物理集群

[完整下载命令](manual-prerequisites.md) 用 curl/SHA 获取 chart 0.9.0、工具和 K3s；用 docker pull 固定 digest，Docker save / k3s ctr import 供 chart 使用；OpenLDAP 从固定 Debian base + 17 deb docker build。完成相应脚本或手工安装后，执行以下只读检查；这些检查不会下载包或初始化集群：

~~~bash
helm show chart "$DPS_RUNTIME_ROOT/dps-install/packages/dps-0.9.0.tgz"
docker image ls --digests
systemctl is-active k3s
kubectl --context "$DPS_KUBE_CONTEXT" get nodes -o wide
kubectl get storageclass
~~~

预期原生物理节点 Ready，K3s v1.34.12+k3s1、Helm 3.22.0、kubectl 1.34.12、local-path；不用 k3d/kind。chart SHA 为 2fc7b6e098b17085bf9aaf010d86dfeaf62677fd0f80bb4c2702e91b0b3fd6ef。

## 2. 可选：独立 PostgreSQL 与 OpenLDAP

只新建缺少的对应服务即可。先配置 deployment.yaml 并完成根 installstep 的第 0 节与第 1 节主机依赖；随后在以下两种方式中选择一种：

**脚本安装：** 每条命令都自行完成对应组件的下载/构建、密码/CA/配置与 Secret YAML、Compose 启动及基本只读自检，无需先执行完整手册生成 Compose。

~~~bash
# 只运行需要新建的服务；已有服务直接对接。
bash dps-install/scripts/install-postgresql.sh --config "$DPS_SOURCE_ROOT/deployment.yaml"
bash dps-install/scripts/install-ldap.sh --config "$DPS_SOURCE_ROOT/deployment.yaml"
~~~

**手工安装：** 改为完整执行 [PG 手册第 1–4 节](manual-postgresql.md) 或 [LDAP 手册第 1–4 节](manual-ldap.md)；LDAP 手工路径先构建固定镜像。两份手册第 4 节都已启动服务。无论选择哪条路线，完成后不要再生成身份或重复启动。下面分别检查本 Lab 的两个服务，只执行自己新建或已有的本地 Lab 组件对应代码块；客户远端服务使用对接指南检查其实际地址：

**安装了本 Lab PostgreSQL 时：**

~~~bash
docker compose -p "$DPS_PG_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/dps-install/config/postgresql/compose.yaml" ps
docker exec -u postgres "$DPS_PG_CONTAINER" psql -d postgres -Atc \
  "select datname,pg_get_userbyid(datdba) from pg_database where datname like 'dps%';"
~~~

**安装了本 Lab LDAP 时：**

~~~bash
docker compose -p "$DPS_LDAP_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/dps-install/config/ldap/compose.yaml" ps
LDAPTLS_CACERT="$DPS_RUNTIME_ROOT/dps-install/config/ldap/tls/ca.crt" LDAPTLS_REQCERT=demand \
  ldapwhoami -x -H "ldaps://$DPS_HOST_IP:$DPS_LDAP_PORT" \
  -D "uid=dps-lab,ou=users,dc=dps,dc=lab" \
  -y "$DPS_RUNTIME_ROOT/dps-install/config/ldap/user.password"
~~~

组件脚本不创建集群 Secret、不装 K3s/DPS；后续按 DPS 手册或 [对接指南](existing-infrastructure.md) 使用已生成的真实凭据/CA，准备 namespace 内 Secret 与 values。独立组件先启动后不能接续整套 install-from-zero 初始化，选择本节组件路线就按后续分步流程完成 DPS。

本 Lab 预期 PG17.11 四库 Owner dps/非 superuser，TLS verify-full/SCRAM；LDAP2.6.10 真实用户/授权组、只读 bind、仅 LDAPS。Core/PowerSteering 两层内建 PostgreSQL 关闭。LDAP 用户与 BMC 凭据分开；组外身份可登录取得无角色 token，但受保护接口拒绝。

## 3. 必需：按实际配置准备 Secret、values 与 Helm

[DPS 手册](manual-install.md) 完整列出本 Lab 的 13 个 kubectl create secret --from-file 命令与每个键，CA/Agent mTLS/JWT/S3，以及 source values.example.yaml 的显式参数渲染。复用外部服务时也要在目标 namespace 创建或引用对应凭据与证书 Secret，具体取舍见 [对接指南](existing-infrastructure.md)。密码不入 values、argv 或日志。

本节安装按 [DPS 手册第 1–5 节](manual-install.md) 完成证书/身份、namespace Secret、values 与原生 Helm。前置条件及 Secret 已全部准备好时，第 5 节的 Helm 安装动作也可替换为下面脚本；不用再重复运行手册的 Helm 命令：

~~~bash
bash dps-install/scripts/install-dps.sh --config "$DPS_SOURCE_ROOT/deployment.yaml"
~~~

仅安装 DPS 的脚本针对本机原生 K3s + Lab LDAP/PRS values，不替代前面的身份、配置和 Secret 准备。组件脚本已经生成的 PG/LDAP/BMC 密码和 CA 继续保留，按手册/对接指南创建或引用相应 Secret；不能再次执行手工章节中的初始密码生成。客户自己的基础设施组合继续使用对接指南的原生 Helm。

**安装后只读检查：**

~~~bash
kubectl -n "$DPS_NAMESPACE" get secret
helm --kube-context "$DPS_KUBE_CONTEXT" -n "$DPS_NAMESPACE" status "$DPS_RELEASE"
kubectl -n "$DPS_NAMESPACE" get pods,pvc
~~~

先检查 API/UI Host 路由归属，另一 namespace/release 占用时拒绝部署。本 Lab 预期 deployed，Core/Agent/UI、Power Config/Controller2.1.0、SeaweedFS4.18 共9工作负载 Ready；Core1PVC、S3三PVC（1Gi/1Gi/10Gi）Bound。实际 logs emptyDir。Template成功与运行验收分别记录。

## 4. 本 Lab 示例：登录、模拟拓扑与 PRS

整套 Lab 脚本成功时已经完成登录、设备登记、inactive 拓扑导入和 PRS 参数设置，直接检查即可。分组件/手工路线在 Helm 就绪后按 [DPS 手册第 6–8 节](manual-install.md) 安装/配置 CLI 与 DNS/CA、真实 LDAP 登录、登记设备/拓扑并设置所选 PRS 参数。这些都是相应安装阶段，不是验收命令；已完成则不重复导入或更新。

**完成登录和登记后的只读检查：**

~~~bash
dpsctl server-version
dpsctl agent list
dpsctl topology list
dpsctl settings list
~~~

本 Lab 预期真实 LDAP admin、Agent connected、110 实体/72计算节点/4rack、inactive、PRS=true。安装新客户端与 DNS/CA 操作见手册。AgentId 在 Topology.Entities，必须用官方 GetTopologyModel 回读72条；CLI export省字段、CLI update实测缺陷的安全手工 current hash 更新也在手册。

真实 BMC 应使用实际硬件的 URL、认证、设备模型、拓扑和 AgentId，跳过 4 rack 模拟蓝图；PRS 按业务选择启用及参数。本 Lab 默认不 activate、不建资源组、不写 BMC；无活跃PRS domain不能宣称动态功率控制通过。独立网络/身份/S3/PG检查与备份见 [verification](../verification/README.md)。

## 现有实例维护与历史

现有身份/data保留，跳过全部首次创建；日常使用 docker compose ps、kubectl/helm status、dpsctl 查询即可。旧 LDAP迁移/PRS启用/故障修复/验收日期完整在 [operation-history](../docs/operation-history.md)。可选工具 [scripts](scripts/README.md) 不作为手工安装依赖；验证报告也不作为安装输入。

当前新实例生产/维护与 [from-zero.md](from-zero.md) 的验证边界分开。访问账号的私密文件为 runtime/config/dps-access.json，DPSCTL token为 runtime/config/dpsctl/credentials.yaml，目录700/文件600。客户端API/UI解析到deployment host_ip并信任 runtime/config/tls/ca.crt。
