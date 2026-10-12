# DPS 0.9 手工安装与独立前置组件

首次部署先读根 [installstep.md](../installstep.md)。这里只使用手工原生命令：配置和下载→独立 PG/LDAP→13 Secret→values/Helm→真实 LDAP登录→inactive 拓扑/PRS。长步骤分别在 [主机/K3s](manual-prerequisites.md)、[PG](manual-postgresql.md)、[LDAP](manual-ldap.md)、[DPS](manual-install.md)。

## 路径与配置

唯一可编辑的部署参数是源码根 [deployment.yaml](../deployment.yaml)。读取：

~~~bash
# 先进入实际 clone 的仓库根目录。
DPS_SOURCE_ROOT=$(git rev-parse --show-toplevel)
source "$DPS_SOURCE_ROOT/dps-install/scripts/deployment-env.sh"
~~~

Git 跟踪 dps-install 的公开 config 模板、artifact-sources.json、LDAP 构建配方与脚本。运行时输入是 $DPS_RUNTIME_ROOT/dps-install/config；下载包是 runtime/dps-install/packages；数据库、K3s、备份是 runtime/dps-install/data。runtime_root由用户选择：.runtime为仓库内专用子目录，.为源码与运行材料同根，/srv/dps-lab为自选绝对目录，源码上级目录也可用。配置中的相对路径按deployment.yaml所在目录解析；live values/真实 Secret、密码、证书/私钥和 kubeconfig 均排除 Git。

## 1. 下载与物理集群

[完整下载命令](manual-prerequisites.md) 用 curl/SHA 获取 chart 0.9.0、工具和 K3s；用 docker pull 固定 digest，Docker save / k3s ctr import 供 chart 使用；OpenLDAP 从固定 Debian base + 17 deb docker build。必要原生检查：

~~~bash
helm show chart "$DPS_RUNTIME_ROOT/dps-install/packages/dps-0.9.0.tgz"
docker image ls --digests
systemctl is-active k3s
kubectl --context "$DPS_KUBE_CONTEXT" get nodes -o wide
kubectl get storageclass
~~~

预期原生物理节点 Ready，K3s v1.34.12+k3s1、Helm 3.22.0、kubectl 1.34.12、local-path；不用 k3d/kind。chart SHA 为 2fc7b6e098b17085bf9aaf010d86dfeaf62677fd0f80bb4c2702e91b0b3fd6ef。

## 2. 独立 PostgreSQL 与 OpenLDAP

分别按 [PG 手册](manual-postgresql.md)、[LDAP 手册](manual-ldap.md) 执行 openssl CA/leaf、随机密码、CREATE ROLE/DATABASE、slappasswd/LDIF/ACL、Compose 明确配置。下面是启动与检查入口，不能替代首次配置步骤：

~~~bash
docker compose -p "$DPS_PG_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/dps-install/config/postgresql/compose.yaml" up -d --wait
docker exec -u postgres "$DPS_PG_CONTAINER" psql -d postgres -Atc \
  "select datname,pg_get_userbyid(datdba) from pg_database where datname like 'dps%';"
docker compose -p "$DPS_LDAP_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/dps-install/config/ldap/compose.yaml" up -d --wait
LDAPTLS_CACERT="$DPS_RUNTIME_ROOT/dps-install/config/ldap/tls/ca.crt" LDAPTLS_REQCERT=demand \
  ldapwhoami -x -H "ldaps://$DPS_HOST_IP:$DPS_LDAP_PORT" \
  -D "uid=dps-lab,ou=users,dc=dps,dc=lab" \
  -y "$DPS_RUNTIME_ROOT/dps-install/config/ldap/user.password"
~~~

预期 PG17.11 四库 Owner dps/非 superuser，TLS verify-full/SCRAM；LDAP2.6.10 真实用户/授权组、只读 bind、仅 LDAPS。Core/PowerSteering 两层内建 PostgreSQL 关闭。LDAP 用户与 BMC 凭据分开；组外身份可登录取得无角色 token，但受保护接口拒绝。

## 3. 原生 Secret、values 和 Helm

[DPS 手册](manual-install.md) 完整列出 13 个 kubectl create secret --from-file 命令与每个键，CA/Agent mTLS/JWT/S3，以及 source values.example.yaml 的显式参数渲染。密码不入 values、argv 或日志。

~~~bash
kubectl -n "$DPS_NAMESPACE" get secret
helm lint "$DPS_RUNTIME_ROOT/dps-install/packages/dps-0.9.0.tgz" \
  -f "$DPS_RUNTIME_ROOT/dps-install/config/values.yaml"
helm template "$DPS_RELEASE" "$DPS_RUNTIME_ROOT/dps-install/packages/dps-0.9.0.tgz" \
  -n "$DPS_NAMESPACE" -f "$DPS_RUNTIME_ROOT/dps-install/config/values.yaml" \
  > "$DPS_RUNTIME_ROOT/verification/logs/dps-rendered.yaml"
helm upgrade --install "$DPS_RELEASE" "$DPS_RUNTIME_ROOT/dps-install/packages/dps-0.9.0.tgz" \
  --kube-context "$DPS_KUBE_CONTEXT" -n "$DPS_NAMESPACE" \
  -f "$DPS_RUNTIME_ROOT/dps-install/config/values.yaml" --wait --timeout 20m --history-max 10
kubectl -n "$DPS_NAMESPACE" get pods,pvc
~~~

先检查 API/UI Host 路由归属，另一 namespace/release 占用时拒绝部署。预期 deployed，Core/Agent/UI、Power Config/Controller2.1.0、SeaweedFS4.18 共9工作负载 Ready；Core1PVC、S3三PVC（1Gi/1Gi/10Gi）Bound。实际 logs emptyDir。Template成功与运行验收分别记录。

## 4. 登录、注册、inactive 拓扑与 PRS

~~~bash
dpsctl --output json login --username dps-lab --password-stdin \
  < "$DPS_RUNTIME_ROOT/dps-install/config/ldap/user.password" \
  > "$DPS_RUNTIME_ROOT/verification/logs/dps-login.json"
jq '.status' "$DPS_RUNTIME_ROOT/verification/logs/dps-login.json"
dpsctl server-version
dpsctl agent list
dpsctl device upsert "$DPS_SOURCE_ROOT/dps-install/config/gb300-power-shelf-devices.yaml"
dpsctl topology validate "$DPS_RUNTIME_ROOT/dps-install/config/topology-4rack-dps09.json"
dpsctl topology import "$DPS_RUNTIME_ROOT/dps-install/config/topology-4rack-dps09.json"
dpsctl settings update --set prs_enabled=true \
  --set prs_headroom_percent=-15 --set prs_scheduler_interval_seconds=5
dpsctl topology list
dpsctl settings list
~~~

预期真实 LDAP admin、Agent connected、110 实体/72计算节点/4rack、inactive、PRS=true。安装新客户端与 DNS/CA 操作见手册。AgentId 在 Topology.Entities，必须用官方 GetTopologyModel 回读72条；CLI export省字段、CLI update实测缺陷的安全手工 current hash 更新也在手册。

默认不 activate、不建资源组、不写 BMC；无活跃PRS domain不能宣称动态功率控制通过。独立网络/身份/S3/PG检查与备份见 [verification](../verification/README.md)。

## 现有实例维护与历史

现有身份/data保留，跳过全部首次创建；日常使用 docker compose ps、kubectl/helm status、dpsctl 查询即可。旧 LDAP迁移/PRS启用/故障修复/验收日期完整在 [operation-history](../docs/operation-history.md)。可选工具 [scripts](scripts/README.md) 不作为手工安装依赖；验证报告也不作为安装输入。

当前新实例生产/维护与 [from-zero.md](from-zero.md) 的验证边界分开。访问账号的私密文件为 runtime/config/dps-access.json，DPSCTL token为 runtime/config/dpsctl/credentials.yaml，目录700/文件600。客户端API/UI解析到deployment host_ip并信任 runtime/config/tls/ca.crt。
