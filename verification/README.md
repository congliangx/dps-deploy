# 独立验证与证据目录

安装步骤在 [installstep.md](../installstep.md)。Git跟踪本目录的可选验收脚本与说明；所有报告、日志、archive和临时文件写入deployment.yaml定义的runtime_root/verification，并排除Git。runtime_root由用户选择：.runtime为仓库内专用子目录，.为源码与运行材料同根，/srv/dps-lab为自选绝对目录，源码上级目录也可用。配置中的相对路径按deployment.yaml所在目录解析。安装不会读取verification报告，不把验证脚本当作必需部署文件。

## 原生只读检查顺序

先读取同一配置，再用原生工具检查独立服务→物理集群→DPS认证/拓扑/PRS，完整输入创建步骤分别在 [BMC](../hardware-sim/manual-install.md)、[PG](../dps-install/manual-postgresql.md)、[LDAP](../dps-install/manual-ldap.md)、[DPS](../dps-install/manual-install.md)。

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

预期单物理节点Ready、9工作负载与4PVC、独立Compose服务、严格TLS、LDAP权限/Agentconnected、inactive拓扑、PRS=true。9个Ready按Deployment/StatefulSet工作负载统计；CronJob产生的Succeeded Pod是正常完成记录，保留，不按全部Pod总数判失败。需要先真实LDAP登录；CLI token和日志600，不能cat凭据/Secret。密码错误/不存在用户被拒绝；有效组外身份可能取得无角色token，受保护API403/RPC AUTHORIZATION_FAILED才是授权检查。

## 验证脚本与输出边界

源码scripts读取source/deployment.yaml和runtime生成输入，默认输出runtime/verification/reports。运行前先阅读源码，确认参数与写操作范围；只有明确支持help并保证退出的入口才可使用--help。多数验证脚本没有参数解析，不能通过--help试探control入口：verify-bmc.py即使带--help也会继续执行PATCH/恢复。状态查询无需全部重跑。

| 脚本类别 | 检查范围 |
| --- | --- |
| verify-prerequisites.py | 历史PRS禁用的Core/Agent/UI三组件前置，固定render3；会创建并清理探针Pod/PVC/ConfigMap，不是纯只读。不能用于当前PRS=true九组件手工链；当前前置使用本文原生命令及组件手册，安装后使用对应部署验收 |
| verify-bmc-inventory.py / verify-agent-pod-bmc.py | 72节点Redfish/TLS/库存/功率GET与实际Pod网络 |
| verify-ldap.py / verify-ldap-auth.py | 独立LDAP与DPS真实身份/授权/会话；UI使用API，无浏览器视觉 |
| DPS/PRS安装验收 | Ready/真实Pod PGverify-full/ControllerLDAP-TLS/S3签名RW/匿名拒绝 |
| 拓扑/路由检查 | 输入结构与原始GetTopologyModel，72AgentId持久关系 |
| 备份检查 | PGdump catalog、LDAP离线slapadd -u；不向运行库覆盖恢复 |

验证入口与部署入口分离。verify-simulator.sh默认只执行库存/遥测GET；control必须明确选择--control，才追加verify-bmc.py的PATCH/恢复。该control入口不属于只读健康复检；先阅读源码和写操作范围，不使用--help试探，不为“验收全跑”默认写BMC。

## 报告索引（全部位于runtime）

| runtime/verification/reports文件 | 证据范围 |
| --- | --- |
| dps-current-state.json / dps-delivery-status.json | 带时间当前汇总，依各子报告日期解释 |
| bmc-health.json / bmc-dps-health-check.json | strictCA72BMC健康/Agent网络与DPS诊断分别标记 |
| verification-inventory.json / dps-pod-bmc-connectivity.json | 详细72Redfish库存与Agent网络GET |
| dps-inactive-topology-limit.json | inactive无法替代Core→Agent深层派发 |
| topology-agent-routing-stored.json / topology-agent-routing-raw-model.json | 原始API路由，不使用会省字段的CLIexport推断 |
| ldap-installation.json / dps-ldap-auth.json | 独立LDAP18/18、2026-10-10上午认证28/28历史快照 |
| prs-databases.json / prs-render.json / prs-installation.json | 2026-10-10三库与实际PRS35/35，render仅静态 |
| from-zero-summary.json | 2026-10-12冷实例PG33/LDAP24/全栈44与46身份重入保持 |
| cold-bootstrap-fullstack.json | runtime主reports中为2026-10-12 12:11迁移后原实例43/43；早晨新实例44/44保留在对应archive内 |
| cold-bootstrap-rerun.json | 早晨冷实例重入详细报告，在对应runtime archive测试实例内 |
| identity-path-migration.json | 2026-10-12 12:07迁移身份/路径11/11，29文件保持 |

报告/日志不默认进入Git；精简摘要与详细材料的实际路径可从runtime报告字段查询。报告文件不是安装依赖。旧来源路径、旧报告与日志留历史/archive，不在源码生成。

2026-10-12迁移后重验：全栈43/43（12:11:53+08）、PRS35/35（12:11:48+08）、身份/路径11/11；保留原密码/CA/JWT和数据。该轮不属于新身份冷部署，具体范围与两处验证器修正见operation-history。

## 已验证与尚未验证

2026-10-10宿主机72端点2232GET、实际Agent Pod72端点1152GET严格TLS健康/库存/功率通过。2026-10-12空源码新身份/新数据复用既有物理K3s的隔离实例44/44，9Ready/0restart，实际PGverify-full/ControllerLDAP/S3/CLI/UI会话通过；46身份文件与DB重入保持。

这些带日期结果完整保存于 [operation-history](../docs/operation-history.md)，不能当作每次环境变更后的重验。该轮没有另一裸OS/K3s首次安装、真实GB300固件、多节点HA或动态功率控制验证。

默认拓扑inactive，0活跃ResourceGroup/PRSdomain；Core→Agent健康派发需active。INVALID_OPERATION/no agent configuration available或SERVER_NOT_STARTED在该状态应如实标待验证，不能合并计入BMC网络Passed。模拟器不强制认证，fixture模型标签/UUID陈旧限制见 [BMC访问](../hardware-sim/bmc-access.md)。
