# 独立验证与证据

安装入口见 [installstep.md](../installstep.md)。本目录跟踪可选验收脚本；报告、日志、archive 和临时材料写入 deployment.yaml 所选 runtime_root/verification，不提交 Git。安装不读取这些报告。布局规则见 [根 README](../README.md)。

## 按安装范围选择

现有脚本主要验收本仓库的 4 rack 模拟器、独立 Docker PG/LDAP、单节点 K3s、PRS/SeaweedFS Lab。72 节点、9 工作负载、4 PVC 和本地 Compose/证书路径只适用于该组合。

客户已有环境按 [对接指南](../dps-install/existing-infrastructure.md) 检查实际 kubeconfig/context、工作负载、存储/Ingress，DPS 到 PG/LDAP/BMC 的网络/TLS，Secret 名称/键/挂载及用户授权、AgentId 路由。启用 PRS 时再检查其数据库和 S3；真实 BMC 不要求模拟器 Compose、/readyz 或 simulator-ca.crt。

## 离线脚本回归

修改脚本后，可在源码根运行：

~~~bash
python3 verification/scripts/verify-script-safety.py --config deployment.yaml
~~~

脚本使用临时配置和 mock 检查帮助/错误参数、工具 PATH、固定镜像、Secret 冲突与 BMC 功率恢复逻辑，不连接实际服务，也不执行安装、下载、登录或功率写入。报告写入所选 runtime 的 verification/reports/script-safety-regression.json；临时测试材料结束后清理。这项检查不能代替实际部署验收。

## Lab 只读状态查询

**先按 [dps-access.md 第 1、3 节](../dps-install/dps-access.md) 加载环境并完成真实 LDAP 登录。** source 环境不会自动登录；有效 CLI 会话是下方 dpsctl 查询的前提。

完整 Lab 安装后在源码根运行下方查询。没有部署某个本地组件时跳过其 Compose/模拟器检查；组件创建步骤在 [BMC](../hardware-sim/manual-install.md)、[PG](../dps-install/manual-postgresql.md)、[LDAP](../dps-install/manual-ldap.md)、[DPS](../dps-install/manual-install.md)。

~~~bash
# 先进入实际 clone 的仓库根目录。
DPS_SOURCE_ROOT=$(git rev-parse --show-toplevel)
source "$DPS_SOURCE_ROOT/dps-install/scripts/deployment-env.sh"
kubectl get nodes -o wide
kubectl -n "$DPS_NAMESPACE" get pods,pvc,service,ingress
helm -n "$DPS_NAMESPACE" status "$DPS_RELEASE"
docker compose -p "$DPS_BMC_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/hardware-sim/runtime/compose.yaml" ps
docker compose -p "$DPS_PG_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/dps-install/config/postgresql/compose.yaml" ps
docker compose -p "$DPS_LDAP_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/dps-install/config/ldap/compose.yaml" ps
openssl verify -CAfile "$DPS_RUNTIME_ROOT/dps-install/config/simulator-ca.crt" \
  -verify_ip "$DPS_HOST_IP" "$DPS_RUNTIME_ROOT/hardware-sim/runtime/tls/tls.crt"
curl -fSs --cacert "$DPS_RUNTIME_ROOT/dps-install/config/simulator-ca.crt" \
  "https://$DPS_HOST_IP:$DPS_BMC_START_PORT/readyz"
dpsctl server-version
dpsctl agent list
dpsctl topology list
dpsctl settings list
~~~


Lab 预期节点 Ready、9 工作负载 Ready、4 PVC Bound、Compose 服务健康、严格 TLS、Agent connected、inactive 拓扑与 PRS=true。工作负载按 Deployment/StatefulSet 统计，CronJob 的 Succeeded Pod 是正常完成记录。

身份验收需区分认证和授权：错误密码/不存在用户应被拒绝；有效组外身份可能得到无角色 token，受保护 API 的 403/RPC AUTHORIZATION_FAILED 才是授权拒绝。凭据、token 和私密日志不输出到共享终端。

## 验证入口与写操作

运行前阅读源码和参数；部分验收会创建探针、登录会话、S3 测试对象或备份文件。状态查询无需重跑全部验收。

| 脚本类别 | 检查范围与边界 |
| --- | --- |
| verify-bmc-inventory.py / verify-agent-pod-bmc.py | 72 节点 Redfish/TLS/库存/功率 GET 与实际 Pod 网络 |
| verify-ldap.py / verify-ldap-auth.py | 独立 LDAP、DPS 认证/授权/会话；UI 使用 API，非浏览器视觉验收 |
| DPS / PRS 验收 | Ready、实际 Pod 的 PG verify-full、Controller LDAP/TLS、S3 签名读写及匿名拒绝 |
| 拓扑/路由检查 | 输入结构、原始 GetTopologyModel 和 72 AgentId 持久关系 |
| 备份检查 | PG dump catalog、LDAP 离线 slapadd -u，不覆盖运行数据库 |
| verify-prerequisites.py | 历史 PRS 关闭的三组件检查，创建并清理探针 Pod/PVC/ConfigMap；不用于当前 PRS=true Lab |

模拟器日常库存/遥测验收入口：

~~~bash
bash verification/scripts/verify-simulator.sh --config deployment.yaml
~~~

该入口默认只对 BMC 执行 GET，报告和日志写入 runtime。--control 会额外调用 verify-bmc.py 执行功率 PATCH/恢复，属于单独授权的控制测试，不是健康查询。直接调用 verify-bmc.py 同样必须显式传入 --control；--help 和未授权默认调用不会进行控制写入。控制检查使用外部 BMC CA，恢复时会逐个尝试所有已修改节点并记录失败。

## 报告在哪里

所有文件位于 runtime/verification/reports；具体报告带时间，旧测试实例与完整证据可能在对应 archive。常用索引：

| 文件 | 范围 |
| --- | --- |
| dps-current-state.json / dps-delivery-status.json | 当前汇总，按子报告时间解释 |
| bmc-health.json / bmc-dps-health-check.json | BMC 健康、Agent 网络与 DPS 诊断 |
| verification-inventory.json / dps-pod-bmc-connectivity.json | 72 Redfish 库存与 Agent 网络 GET |
| topology-agent-routing-stored.json / topology-agent-routing-raw-model.json | 原始 API 路由，不用省略字段的 CLI export 推断 |
| ldap-installation.json / dps-ldap-auth.json | LDAP 服务与 DPS 身份验收 |
| prs-databases.json / prs-render.json / prs-installation.json | PRS 数据库、静态渲染与运行验收 |
| from-zero-summary.json / cold-bootstrap-fullstack.json / cold-bootstrap-rerun.json | 隔离实例、重入或原实例验收；具体实例和时间以报告为准 |
| identity-path-migration.json | 运行目录迁移后的身份/路径检查 |

cold-bootstrap-fullstack.json 在主 reports 中记录原实例迁移后检查；早晨隔离新实例的报告和重入证据保存在其 archive 中。不要仅凭文件名把两轮结果混用。

## 已验证范围与限制

带日期的验证、修复与迁移结果见 [操作历史](../docs/operation-history.md)，不作为后续变更后的最新验收。已验证模拟器严格 TLS GET/库存、隔离 Lab 集成和身份/数据重入保留；该轮复用已有物理 K3s，未验证另一台空白 OS 首装、真实 GB300 固件、多节点 HA 或动态功率闭环。

当前拓扑 inactive，无活跃 ResourceGroup/PRS domain。Core→Agent 深层派发需 active；INVALID_OPERATION/no agent configuration available 或 SERVER_NOT_STARTED 应标为待验证，不能计入 BMC 网络通过。模拟器认证与 fixture 限制见 [BMC 访问](../hardware-sim/bmc-access.md)。
