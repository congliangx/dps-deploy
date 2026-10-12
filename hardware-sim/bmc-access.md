# 4 rack GB300 BMC 访问与接入说明

首次安装见 [硬件手工步骤](manual-install.md)，整个部署见 [installstep](../installstep.md)。远端ssh root@L20-12；源码 /raid/vince/deploy，运行 /raid/vince/deployed-test，由根 [deployment.yaml](../deployment.yaml) 的runtime_root/host_ip/bmc_start_port决定。

~~~bash
# 先进入实际 clone 的仓库根目录。
DPS_SOURCE_ROOT=$(git rev-parse --show-toplevel)
source "$DPS_SOURCE_ROOT/dps-install/scripts/deployment-env.sh"
~~~

## 地址、规模与必要文件

默认BMC地址为https://10.6.131.43:端口，nginx自动保持唯一节点Host，不需要客户端自设Host/DNS。4rack×18节点，288GPU/144CPU：

| Rack | 节点名称 | 默认端口 |
| --- | --- | --- |
| gb300-rack-01 | gb300-r01-0001–0018 | 18443–18460 |
| gb300-rack-02 | gb300-r02-0001–0018 | 18461–18478 |
| gb300-rack-03 | gb300-r03-0001–0018 | 18479–18496 |
| gb300-rack-04 | gb300-r04-0001–0018 | 18497–18514 |

实际地址查runtime/dps-install/config/bmc-endpoints.csv（600），共享凭据查bmc-credentials.json（600）。新实例随机生成；已有实例继续使用保存凭据。密码不写入Markdown/Git/日志，不把BMC账号当作DPS LDAP/API/UI账号。

| 必要运行输入 | 用途 |
| --- | --- |
| runtime/hardware-sim/runtime/compose.yaml、config.yaml、nginx.conf、nodes.json | 启动与路由72节点 |
| runtime/hardware-sim/runtime/tls | nginx公开CA/leaf和私密leafkey |
| runtime/hardware-sim/runtime/authority | BMC CA签名身份，不挂容器 |
| runtime/dps-install/config/simulator-ca.crt | 外部客户端/DPS信任 |
| runtime/dps-install/config/bmc-shared-secret.yaml / bmc-ca-secret.yaml | 带credentials-store标签的BMCSecret / dps-bmc-ca |
| runtime/dps-install/config/topology-4rack-dps09.json | 当前有效拓扑，72AgentId在Topology.Entities |
| source/dps-install/config/gb300-power-shelf-devices.yaml | 33kW/95%PowerSupply注册 |

source与runtime是上文两个绝对根；下载chart在runtime/dps-install/packages。公开nodes模板在source/hardware-sim/templates/nodes.json。旧SDK/vendor下载不是当前启动依赖，旧拓扑文件仅属于归档，不是安装输入。

## TLS与认证的真实范围

客户端使用runtime/dps-install/config/simulator-ca.crt严格校验IP/SAN，不用curl -k。外部nginxleaf来自项目BMC CA；SDK mock ssl会生成私有backend证书，私有Docker链路proxy_ssl_verify off。只有nginx挂项目leaf/key，CA签名私钥不挂容器；不能声称backend读取项目leaf。

**模拟器不强制认证。** 正确/错误/无Authorization都可GET，SessionService可创建模拟session。测试凭据供DPS接口使用，不证明真实BMC密码校验、安全策略或固件兼容性。

从私密JSON读凭据验证首节点GPU遥测，密码不进入argv/历史：

~~~bash
python3 - <<'PY'
import os,json,base64,ssl,urllib.request
from pathlib import Path
c=Path(os.environ["DPS_RUNTIME_ROOT"])/"dps-install/config"
cred=json.loads((c/"bmc-credentials.json").read_text())
authorization=base64.b64encode((cred["username"]+":"+cred["password"]).encode()).decode()
url=f'https://{os.environ["DPS_HOST_IP"]}:{os.environ["DPS_BMC_START_PORT"]}/redfish/v1/Systems/HGX_Baseboard_0/Processors/GPU_0/EnvironmentMetrics'
req=urllib.request.Request(url,headers={"Authorization":"Basic "+authorization})
with urllib.request.urlopen(req,context=ssl.create_default_context(cafile=str(c/"simulator-ca.crt"))) as r:
 print(json.dumps(json.load(r),indent=2))
PY
~~~

## Redfish与模拟限制

服务根/redfish/v1/；Systems列表中System_0与HGX_Baseboard_0是同一节点两个视图，不是2台设备。HGX系统Processors下GPU_0–3及CPU_0–1提供EnvironmentMetrics。ready/live为/readyz、/livez。单节点4GPU/2CPU，fixtureGPU限制范围200–1400W、默认1400W；synthetic仅模拟功率，内存状态/session在重启后重置。

官方GB300fixture还保留GB200 NVL/Generic等陈旧型号、固定serial/UUID；按公开nodes、拓扑Name、每节点独立状态和4GPU/2CPU结构判断模拟模型。DPS输入Model=DGX_GB300。没有真实GB300硬件和固件验收。

## 原生状态检查与维护

~~~bash
compose="$DPS_RUNTIME_ROOT/hardware-sim/runtime/compose.yaml"
docker compose -p "$DPS_BMC_PROJECT" -f "$compose" ps
docker compose -p "$DPS_BMC_PROJECT" -f "$compose" logs --tail 50
docker exec "$DPS_PROXY_CONTAINER" nginx -t
curl -fSs --cacert "$DPS_RUNTIME_ROOT/dps-install/config/simulator-ca.crt" \
  "https://$DPS_HOST_IP:$DPS_BMC_START_PORT/readyz"
~~~

部署/维护使用同一Compose project；默认dps-gb300-sim，容器名由instance_prefix派生。unless-stopped随Docker启动恢复；明确stop需start恢复。配置修改先审阅并nginx-t/reload，容器重建或restart会重置模拟内存。状态查询不需要重建密码/CA或运行部署脚本。

## DPS接入与验证边界

DPS通过物理原生K3s上的手动Helm部署，真实LDAP/PRS启用，OIDC/Zapp关闭。DPS Agent mTLS connected，拓扑dps-gb300-4rack默认inactive；110实体/72计算节点，官方API/currenthash更新后原始回读72AgentId。安装命令见 [DPS手册](../dps-install/manual-install.md)。

2026-10-10的BMC只读复检：72端点strictCA、ready/live、2Systems/2Managers/HGXchassis、288GPU144CPU Health=OK/State=Enabled和功率遥测，宿主机2232GET；实际Agent Pod网络72/72、1152GET通过。相关报告在runtime/verification/reports/bmc-health.json、verification-inventory.json、dps-pod-bmc-connectivity.json。日期与完整实录见 [operation-history](../docs/operation-history.md)。

宿主机/Agent Pod GET与Core→Agent派发分别报告。inactive下dpsctl check connection返回INVALID_OPERATION/no agent configuration available、check status返回SERVER_NOT_STARTED，不代表独立Pod未Ready。深层Core健康派发需active拓扑；当前MaxLPS激活涉及功率策略，本安装没有激活/写BMC，不能列为通过。PRS无活跃RG/domain，动态闭环尚未验证。

[verification](../verification/README.md) 的topology-check/inventory/control/artifact-version报告均只是验收/追溯，不被BMC启动、DPS安装/拓扑导入读取。生产必要输入与验证文件保持分离。
