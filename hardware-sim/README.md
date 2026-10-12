# 可选 Lab 组件：4 rack GB300 硬件模拟

**有真实 BMC 的环境跳过本目录的全部安装步骤。** 模拟器仅用于本 Lab 缺少 GB300 硬件的情况；DPS 可以直接对接真实硬件，不要求下载 SDK 或部署模拟服务。真实 BMC 用户按 [已有基础设施对接指南](../dps-install/existing-infrastructure.md) 配置 Redfish URL、账号/密码 Secret、受信 CA、设备模型与实际拓扑，并验证 Agent 到 BMC 的网络和 TLS。

本组件使用 SDK 官方 BMC Simulator 0.9，加载 /app/mockups/gb300 + synthetic 插件。4 rack×18节点=72 BMC、288GPU、144CPU；不调用 SDK task deploy/sdk/setup 安装 DPS。公开 nodes/topology 模板与镜像足够启动，无需下载 SDK/vendor。

脚本与手工两种首次安装方式见下文，根流程在 [installstep.md](../installstep.md)；详细命令与各产物说明在 [manual-install.md](manual-install.md)。选择一种安装方式完成后，再执行只读检查。

## 模拟器配置与输入

~~~bash
# 先进入实际 clone 的仓库根目录。
DPS_SOURCE_ROOT=$(git rev-parse --show-toplevel)
source "$DPS_SOURCE_ROOT/dps-install/scripts/deployment-env.sh"
~~~

本模拟器的 Lab 参数从根 [deployment.yaml](../deployment.yaml) 读取，runtime_root由用户选择：.runtime为仓库内专用子目录，.为源码与运行材料同根，/srv/dps-lab为自选绝对目录，源码上级目录也可用。配置中的相对路径按deployment.yaml所在目录解析，生成物不提交Git。公开节点模板 [templates/nodes.json](templates/nodes.json)、DPS拓扑 [topology-4rack-dps09.json](../dps-install/templates/topology-4rack-dps09.json) 在源码。生成Compose/nginx/nodes/TLS在runtime/hardware-sim/runtime，必要凭据/URL/CA/拓扑在runtime/dps-install/config；验证在runtime/verification。

## 安装方式：脚本或手工二选一

先完成根 [installstep.md 第 0 节](../installstep.md) 的参数设置和环境加载，再准备 Docker/Compose、Python/YAML、OpenSSL 主机依赖。单独安装模拟器不需要 K3s、数据库或 DPS；deployment.yaml 中设置主机 IP、端口起点、AgentId、容器/Compose project 和运行目录。

### 脚本安装：一个入口完成准备和启动

~~~bash
bash hardware-sim/scripts/install-bmc.sh \
  --config "$DPS_SOURCE_ROOT/deployment.yaml"
~~~

无需事先运行手册生成 compose.yaml。此入口按顺序：

1. 校验/下载 simulator 与 nginx 两个固定 digest 镜像。
2. 从公开蓝图生成 72 个 URL 和四 rack 拓扑，生成随机 BMC 密码、外部 CA/leaf、凭据清单与 Secret YAML。
3. 写模拟器、nginx 路由和 Compose 配置，启动模拟器与代理。
4. 等待健康，检查 nginx 配置与受信 CA 下的 readiness。

详细参数、动作与产物见 [manual-install.md](manual-install.md)。成功后跳到本页“安装后只读检查”和 DPS 接入，不重复手册第 1–4 节的生成/启动。已有脚本归属实例重入保留原身份；手工或历史实例使用原配置维护。这里仅生成 Secret 文件，不应用到 Kubernetes 或部署 DPS；后续按 DPS 手册/对接指南继续，不调用完整 fresh 脚本接管已启动的组件。

### 手工安装：按手册完整执行

不运行上面的组件脚本，改为执行 [manual-install.md 第 1–4 节](manual-install.md)：下载固定镜像 → 随机密码与外部 CA/leaf → 节点/拓扑/凭据 → nginx/Compose 及启动。第 4 节已经启动服务；完成后直接进行第 5 节或下方只读检查，不再追加执行 docker compose up。

## 安装后只读检查

下面的命令在上述任一安装方式成功后执行；可以重复执行。它们不生成文件、不启动或重启服务，不构成独立安装步骤：

~~~bash
docker compose -p "$DPS_BMC_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/hardware-sim/runtime/compose.yaml" ps
docker exec "$DPS_PROXY_CONTAINER" nginx -t
openssl verify -CAfile "$DPS_RUNTIME_ROOT/dps-install/config/simulator-ca.crt" \
  -verify_ip "$DPS_HOST_IP" "$DPS_RUNTIME_ROOT/hardware-sim/runtime/tls/tls.crt"
jq 'length' "$DPS_RUNTIME_ROOT/hardware-sim/runtime/nodes.json"
stat -c '%a %n' "$DPS_RUNTIME_ROOT/dps-install/config/bmc-endpoints.csv" \
  "$DPS_RUNTIME_ROOT/dps-install/config/bmc-credentials.json"
curl -fSs --cacert "$DPS_RUNTIME_ROOT/dps-install/config/simulator-ca.crt" \
  "https://$DPS_HOST_IP:$DPS_BMC_START_PORT/readyz"
curl -fSs --cacert "$DPS_RUNTIME_ROOT/dps-install/config/simulator-ca.crt" \
  "https://$DPS_HOST_IP:$DPS_BMC_START_PORT/redfish/v1/Systems/HGX_Baseboard_0" |
  jq '{Id,Status}'
~~~

预期两个 Docker 服务健康、证书 OK、节点计数 72、凭据文件 600，以及第一个入口的 readiness/Redfish 响应；这组简短检查不代表全部 72 节点的库存和动态控制验收。详细健康/库存/Agent GET 在 [verification](../verification/README.md)，不是安装依赖。默认 72 个端口为 18443–18514，配置可改；每 URL 不需要客户端自设 Host，代理自动映射唯一节点。外部严格校验项目 CA，私有 backend 自动证书与 proxy_ssl_verify off 的范围另见手册。

## DPS 接入与维护

BMC Secret/CA、33kW/95%电源类型、AgentId关系与inactive拓扑导入在 [DPS手册](../dps-install/manual-install.md)。后续DPS安装需要runtime中的Secret/CA/拓扑；verification的JSON报告不需要。

只查状态用docker compose ps/logs；明确stop后可start恢复，restart会丢模拟器内存功率/session状态。两服务unless-stopped。不用维护操作重新生成密码/CA。读取URL/用户密码见 [bmc-access.md](bmc-access.md)；密码不入Markdown、Git或日志。

模拟器不强制认证且保留官方fixture陈旧型号/UUID标签；实机GB300、固件和BMC认证不在模拟验证范围。默认inactive、不做PATCH；Agent网络GET与Core→Agent派发/动态功率控制分别报告。
