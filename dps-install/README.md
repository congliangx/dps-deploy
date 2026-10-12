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

真实 BMC 使用实际设备模型、拓扑和凭据；PRS 按业务需求选择。初次安装默认保持拓扑 inactive，不创建资源组；以下激活与 PRS 配置属于单独的运维步骤，会向 BMC 下发功率策略。

## 5. 运维：激活拓扑与 PRS 资源组

本节使用 DPS 0.9 原生 CLI，将已登记节点加入一个资源组，采用 MaxLPS 并启用 DPM、PRS 和共享 GPU。当前 L20-12 的 dps-gb300-4rack 拓扑及 dps-gb300-4rack-prs 资源组已经 active，包含 72 个模拟计算节点；**该实例直接执行第 5.5 节的只读检查，不重复创建或激活。** 客户环境先确定节点选择与业务功率策略，不能直接沿用 Lab 的整拓扑分组。以下命令分段执行，任何检查失败时停止后续写入并保留响应。

### 5.1 加载环境、登录并核对现状

在部署主机的 Bash 会话中，进入源码根目录。以下账号沿用现有 LDAP 身份，不重新生成密码；客户已有身份按 [访问指南](dps-access.md) 登录。

~~~bash
DPS_SOURCE_ROOT=$(git rev-parse --show-toplevel)
source "$DPS_SOURCE_ROOT/dps-install/scripts/deployment-env.sh" \
  --config "$DPS_SOURCE_ROOT/deployment.yaml"
bash dps-install/scripts/dps-login.sh --config "$DPS_DEPLOYMENT_CONFIG"
umask 077
op="$DPS_RUNTIME_ROOT/verification/archive/prs-manual/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$op"
dpsctl --output json topology list > "$op/topologies.json"
dpsctl --output json resource-group list > "$op/groups.json"
dpsctl --output json settings list > "$op/settings.json"
jq '.topologies' "$op/topologies.json"
jq '.resource_groups // []' "$op/groups.json"
jq '.settings | {prs_enabled, prs_headroom_percent, prs_scheduler_interval_seconds}' "$op/settings.json"
~~~

确认目标拓扑、已有资源组及持久 PRS 开关。当前 Lab 已是 prs_enabled=true；如果实际为 false，单独执行以下变更后再检查，不修改其他调度参数：

~~~bash
# 仅全局 prs_enabled=false 且需要启用 PRS 时执行。
dpsctl settings update --set prs_enabled=true
dpsctl --output json settings list > "$op/settings.json"
jq -e '.settings.prs_enabled == "true"' "$op/settings.json"
~~~

变更前可备份本 Lab 的 Core 与三个 PRS 数据库；客户已有数据库使用自己的备份流程：

~~~bash
bash dps-install/scripts/postgresql-backup.sh --config "$DPS_DEPLOYMENT_CONFIG"
bash dps-install/scripts/postgresql-backup-prs.sh --config "$DPS_DEPLOYMENT_CONFIG"
~~~

### 5.2 首次激活拓扑

先确认目标只有一条记录。**已经 active 时跳过激活动作；已有其他 active 拓扑时停止，不能自动 deactivate。** 激活会应用拓扑默认策略；要求全部目标 BMC 连通。

~~~bash
jq -e --arg t "$DPS_TOPOLOGY_NAME" \
  '[.topologies[] | select(.topology_name == $t)] | length == 1' "$op/topologies.json"
if jq -e --arg t "$DPS_TOPOLOGY_NAME" \
    '.topologies[] | select(.topology_name == $t) | .is_active == true' \
    "$op/topologies.json" >/dev/null; then
  printf '目标拓扑已经 active，跳过激活。\n'
else
  jq -e '[.topologies[] | select(.is_active == true)] | length == 0' "$op/topologies.json" &&
  dpsctl --no-retry --grpc-timeout 180s --output json topology activate \
    --topology "$DPS_TOPOLOGY_NAME" --ping-hosts --at-least-percent-hosts 100 \
    > "$op/topology-activate.json"
fi
dpsctl --output json topology list --active=true > "$op/active-topology.json"
~~~

首次激活响应应为 status.ok=true，且每个 node_statuses 项的 status.ok=true。若失败，先检查响应和 BMC 连通性，不重试或自动切换其他拓扑。

### 5.3 选择节点，创建资源组并加入成员

以下 Lab 示例选取目标 active 拓扑的全部 leaf_node_names，检查非空、唯一及数量。当前应为 72；客户需按工作负载选择实际节点子集，不能将 72 当作通用要求。资源组名和 external ID 必须与现有组都不冲突；同名组已存在时停止创建，改为检查既有组。

~~~bash
RG_NAME="${DPS_TOPOLOGY_NAME}-prs"
RG_EXTERNAL_ID=1
RG_NODES=$(jq -er --arg t "$DPS_TOPOLOGY_NAME" '
  [.topologies[] | select(.topology_name == $t and .is_active == true)] |
  if length == 1 then .[0].leaf_node_names |
    if length > 0 and length == (unique | length) then join(",")
    else error("节点为空或重复") end
  else error("目标 active 拓扑不唯一") end' "$op/active-topology.json")
RG_NODE_COUNT=$(awk -F, '{print NF}' <<< "$RG_NODES")
printf '组名=%s external ID=%s 节点数=%s\n%s\n' \
  "$RG_NAME" "$RG_EXTERNAL_ID" "$RG_NODE_COUNT" "$RG_NODES"
dpsctl --output json resource-group list > "$op/groups.json"
if jq -e --arg rg "$RG_NAME" --argjson id "$RG_EXTERNAL_ID" \
    '(.resource_groups // []) | all(.group_name != $rg and .external_id != $id)' "$op/groups.json"; then
  dpsctl --no-retry --grpc-timeout 210s --output json resource-group create \
    --resource-group "$RG_NAME" --external-id "$RG_EXTERNAL_ID" --policy-bundle MaxLPS \
    --dpm-enable=true --prs-enabled=true --shared-gpu-enable=true > "$op/rg-create.json" &&
  jq -e '.status.ok == true' "$op/rg-create.json" &&
  dpsctl --no-retry --grpc-timeout 210s --output json resource-group add \
    --resource-group "$RG_NAME" --entities "$RG_NODES" > "$op/rg-add.json" &&
  jq -e '.status.ok == true' "$op/rg-add.json"
else
  printf '组名或 external ID 已存在，停止创建；核对既有组后执行只读检查。\n'
fi
dpsctl --output json resource-group list > "$op/rg-prepared.json"
jq --arg rg "$RG_NAME" \
  '.resource_groups[] | select(.group_name == $rg)' "$op/rg-prepared.json"
~~~

**每条检查成功后才执行下一条。** 激活前核对 resource_names 与所选节点完全一致，以及 policy_bundle=MaxLPS、prs_enabled/dpm_enable/shared_gpu_enable=true、activation_status=inactive。DPS 0.9 必须在 create 时指定 policy bundle，不能在 activate 后通过 update 补设。新组为空时 add 成员；既有组不重复 add，也不自动移除成员。

### 5.4 激活资源组并检查每个节点结果

~~~bash
jq -e --arg rg "$RG_NAME" --arg nodes "$RG_NODES" '
  [.resource_groups[] | select(.group_name == $rg)] | length == 1 and
  all(.[]; .activation_status == "inactive" and .policy_bundle == "MaxLPS" and
    .prs_enabled == true and .dpm_enable == true and .shared_gpu_enable == true and
    (.resource_names | sort) == ($nodes | split(",") | sort))' "$op/rg-prepared.json" &&
dpsctl --no-retry --grpc-timeout 210s --output json resource-group activate \
  --resource-group "$RG_NAME" --sync --strict-policy --allow-reprovision=false \
  --at-least-percent-hosts 100 --partial-timeout 180s > "$op/rg-activate.json"
jq -e --argjson n "$RG_NODE_COUNT" '
  .status.ok == true and (.node_statuses | length) == $n and
  all(.node_statuses[];
    .policy_apply_status.status.ok == true and
    .gpu_power_policy_results.status.ok == true and
    all(.gpu_power_policy_results.gpu_power_policy_result[]; .ok == true) and
    .cpu_policy_result.ok == true and .node_policy_result.ok == true)' "$op/rg-activate.json"
~~~

RG 激活响应的节点状态在 policy_apply_status.status，和拓扑激活的节点 status 字段不同。失败时保留响应并排查，不开启自动重试或 reprovision。

### 5.5 安装后的只读检查

新会话先执行第 5.1 节的环境加载与登录，然后查询：

~~~bash
RG_NAME="${DPS_TOPOLOGY_NAME}-prs"
dpsctl --output json topology list --active=true
dpsctl --output json resource-group list |
  jq --arg rg "$RG_NAME" '.resource_groups[] | select(.group_name == $rg)'
dpsctl --grpc-timeout 210s check connection --topology "$DPS_TOPOLOGY_NAME"
~~~

确认目标拓扑和资源组均 active、成员数量正确、三个开关为 true、BMC 连通。DPS 将 PRS 资源组同步为 PRS domain，无需手工创建 domain；PRS 服务就绪和组激活成功，仍需结合 domain/node 遥测、实际 GPU 功率与调度结果验证动态闭环。初次安装的“无资源组、inactive”验收不再适用于执行本节后的实例。当前 L20-12 已确认 1 个 active 资源组、1 个 running domain、72 节点/288 GPU，调度与模拟 BMC 的自动功率分配已观测；这不等同于真实负载的性能或节能验收。

## 后续维护与验证

访问材料在 $DPS_RUNTIME_ROOT/dps-install/config，账号为 dps-access.json，CLI 会话为 dpsctl/credentials.yaml，CA 为 tls/ca.crt；生成阶段、权限与访问步骤见 [dps-access.md](dps-access.md)。

按实际安装范围执行 [验证](../verification/README.md)，维护工具见 [脚本索引](scripts/README.md)。验证报告不作为安装输入。已有实例跳过初次创建，保留身份/data；带日期的 LDAP/PRS 变更与验收见 [操作历史](../docs/operation-history.md)。
