# 四个 GB300 rack 的 SDK BMC 模拟环境

首次从仓库创建新的四 rack 模拟器使用 [从零部署](../dps-install/from-zero.md) 的 prepare-bmc-fresh.py：生成新的模拟凭据和对外 CA/证书，不依赖本机旧 SDK/vendor。以下地址与凭据说明属于 L20-12 已运行实例。

远程主机：`root@L20-12`（管理 IP `10.6.131.43`）；工作目录：`/raid/vince/deploy`。

## 已部署内容

官方 `dps-bmc-simulator:0.9.0` 的 `/app/mockups/gb300` 模型与 synthetic 功率遥测插件；Docker Compose 独立运行，不依赖 Kubernetes。一个模拟器后端通过 nginx 为 72 个节点保留各自 Host，提供相互独立的功率控制状态。

本目录仅运行硬件模拟器及 HTTPS 路由。DPS 0.9 已通过手动 Helm 安装在 L20-12 物理机原生 K3s，当前 release 为 revision 5，独立 LDAP 与 PRS/PowerSteering 已启用；OIDC 和 Zapp 保持关闭。独立 PostgreSQL、LDAP、DPS 配置与安装脚本位于 `dps-install/`。SDK 原件位于 `hardware-sim/dps-sdk/`，DPS chart 位于 `dps-install/packages/dps-0.9.0.tgz`，内容保留，未执行任何 SDK task deploy/sdk/setup。

| Rack | 节点名称 | HTTPS 端口 | 计算节点 / GPU / CPU |
|---|---|---|---|
| gb300-rack-01 | gb300-r01-0001 至 gb300-r01-0018 | 18443–18460 | 18 / 72 / 36 |
| gb300-rack-02 | gb300-r02-0001 至 gb300-r02-0018 | 18461–18478 | 18 / 72 / 36 |
| gb300-rack-03 | gb300-r03-0001 至 gb300-r03-0018 | 18479–18496 | 18 / 72 / 36 |
| gb300-rack-04 | gb300-r04-0001 至 gb300-r04-0018 | 18497–18514 | 18 / 72 / 36 |

BMC URL 格式为 `https://10.6.131.43:端口`。首节点例：`https://10.6.131.43:18443`。不需要安装 DNS 或修改 DPS Pod 的 hosts 文件，也无需额外发送 Host header；路由已自动映射节点身份。

## 账号、密码与 TLS

全部节点的 URL、用户名、密码存放于 `dps-install/config/bmc-endpoints.csv`（权限 600）。共享测试凭据位于 `dps-install/config/bmc-credentials.json`（权限 600），沿用官方 0.9.0 simulator chart 的 BMC Secret 值。

**模拟器没有强制认证。** 实测正确测试凭据、错误凭据、无 Authorization 均可读取 Redfish；SessionService 创建返回 201。这些是模拟接口可接受的测试凭据，不代表真实 BMC 的密码校验或安全行为。凭据不属于 DPS API/UI 账号。

HTTPS 使用本项目自签证书，客户端应信任 `dps-install/config/simulator-ca.crt`；已安装的 DPS values 通过 BMC CA Secret 校验证书。2026-10-09 实际 Agent Pod 网络 namespace 到全部 72 个 BMC 的 HTTPS CA、288 GPU/144 CPU 清单和功率遥测检查通过，共 1152 次只读 GET，报告为 `verification/reports/dps-pod-bmc-connectivity.json`。该检查使用现有 Pod 网络，没有修改 Pod spec 或写 BMC；它验证 Agent Pod 到 BMC 的网络/Redfish，Core→Agent→BMC 派发仍待拓扑激活后验收。

读取首节点 GPU 遥测（从文件加载凭据，不将密码写进命令历史）：

```bash
cd /raid/vince/deploy
python3 - <<'PY'
import base64, json, ssl, urllib.request
c=json.load(open('dps-install/config/bmc-credentials.json'))
token=base64.b64encode((c['username']+':'+c['password']).encode()).decode()
u='https://10.6.131.43:18443/redfish/v1/Systems/HGX_Baseboard_0/Processors/GPU_0/EnvironmentMetrics'
r=urllib.request.Request(u,headers={'Authorization':'Basic '+token})
with urllib.request.urlopen(r,context=ssl.create_default_context(cafile='dps-install/config/simulator-ca.crt')) as res:
    print(json.dumps(json.load(res),indent=2))
PY
```

## Redfish 接口

- 服务根：`/redfish/v1/`
- 系统列表：`/redfish/v1/Systems`（System_0 和 HGX_Baseboard_0 属于同一计算节点，不是两个物理节点）
- GPU 所在系统：`/redfish/v1/Systems/HGX_Baseboard_0`
- 处理器列表：`/redfish/v1/Systems/HGX_Baseboard_0/Processors`
- GPU 遥测及功率限制：`/redfish/v1/Systems/HGX_Baseboard_0/Processors/GPU_0/EnvironmentMetrics`（GPU_0 至 GPU_3）
- 修改限制：PATCH 上述接口，请求体示例 `{"PowerLimitWatts":{"SetPoint":700}}`。
- 健康检查：`/readyz`、`/livez`

官方 fixture 的 GPU 功率限制范围为 200–1400 W，默认 1400 W；synthetic 插件产生模拟功率变化，不代表真实硬件或真实工作负载。节点功率限制和 session 状态在模拟器内存中，重启后恢复初始模拟状态。

上游 0.9.0 的 GB300 mockup 存在陈旧标签：ServiceRoot.Product / ComputerSystem.Model 仍显示 `GB200 NVL`，GPU Model 为 `Generic`，序列号和 UUID 也复用固定 fixture 值。节点身份以交付清单、拓扑 Name 及独立功率状态区分。本次保留官方 fixture，实际已加载 GB300 mockup（每节点 4 GPU、2 CPU）；DPS 导入文件将节点型号明确设置为 `DGX_GB300`。通过 mockup 选择、设备结构及功率接口验证模型，不将陈旧字符串当作 GB200 部署。没有真实硬件和固件兼容性验证。

## 启动与维护

```bash
cd /raid/vince/deploy
./hardware-sim/scripts/bmc-simulator.sh status
./hardware-sim/scripts/bmc-simulator.sh logs
./hardware-sim/scripts/bmc-simulator.sh stop
./hardware-sim/scripts/bmc-simulator.sh start
./hardware-sim/scripts/bmc-simulator.sh restart
```

Compose 文件：`hardware-sim/runtime/compose.yaml`；Docker 项目：`dps-gb300-sim`；容器：`dps-gb300-bmc`、`dps-gb300-bmc-proxy`；网络：`dps-gb300-bmc-net`。Docker 服务已设开机启用，两容器使用 `unless-stopped`，若未手动停止会在 Docker/主机启动后恢复。手动 stop 后使用 start 恢复。

可选验证统一位于 `verification/`，见 [验证说明](../verification/README.md)。启停脚本只管理模拟器，不调用验证脚本。

## DPS 安装与接入文件

安装输入集中在 `/raid/vince/deploy/dps-install/`，详见 [DPS 安装文件说明](../dps-install/README.md)：

- `packages/dps-0.9.0.tgz`：DPS 0.9 Helm chart。
- `config/topology-4rack-dps09.json`：当前有效的 DPS 0.9 4-rack GB300 导入/更新输入，72 个节点的 AgentId 位于 `Topology.Entities` 关系对象，目标为 `gb300-lab-agent`。旧版拓扑输入仅保留在验证归档中。
- `config/bmc-shared-secret.yaml`：拓扑引用的共享 BMC Secret；已应用到dps namespace，含credential store所需标签。
- `config/bmc-endpoints.csv`、`config/bmc-credentials.json`：逐节点地址和测试凭据，供查阅/配置客户端。
- `config/simulator-ca.crt`：需要信任自签 TLS 时使用的公开证书。

`verification/reports/` 中的拓扑检查、接口检查、功率检查及版本追溯 JSON 都是验证材料，后续 DPS 安装和拓扑导入不读取它们。

DPS 拓扑 `dps-gb300-4rack` 已校验并导入，110 个实体、72 个计算节点在 UI 可见；通过官方 API 与当前 hash 校验更新后，已回读确认全部 72 条 Agent 路由。拓扑保持 inactive，Agent mTLS 已连接，但尚未下发设备配置。DPS 的拓扑连接和深层 BMC 健康检查要求激活拓扑；当前激活会应用 MaxLPS 功率策略，本轮没有执行，Core→Agent→BMC 派发及动态功率控制尚未验收。

2026-10-10 17:28–17:32 +08:00 独立 BMC 健康复检已完成：72/72 节点严格 CA 校验、ready/live、Redfish 系统/BMC Manager/chassis/288 GPU/144 CPU 健康与有效功率遥测通过，主机共 2232 GET；实际 Agent Pod 网络 72/72 端点、1152 GET 通过。独立服务/Pod Ready 检查 12/12 通过。结果见 `verification/reports/bmc-health.json`，所有细项仅在 verification。DPS 实际连接诊断返回 INVALID_OPERATION（no agent configuration available），节点状态查询返回 SERVER_NOT_STARTED；当前拓扑 inactive，未下发设备配置，Core→Agent→BMC 健康派发不列为通过。未重启服务或写入功率。

四个 rack 按节点及 PSU 名称、FloorPDU 归属建模，不额外创建 Rack 类型实体。实际操作记录仍在根目录 `installstep.md`。

## 重建配置

```bash
cd /raid/vince/deploy
python3 hardware-sim/scripts/generate-topology.py
python3 hardware-sim/scripts/configure-bmc-proxy.py
./hardware-sim/scripts/bmc-simulator.sh start
```

硬件目录内 `runtime/` 保存 Compose、配置、节点映射和 TLS，`scripts/` 保存生成与启停脚本，`dps-sdk/` 保存 SDK，`vendor/` 保存模拟器 chart 和上游配置。镜像按 digest 固定，上游原文件均保留。证书和 hardware-sim/runtime/config.yaml 已保存；重建时继续使用现有文件。配置更改后执行 `docker compose -p dps-gb300-sim -f hardware-sim/runtime/compose.yaml up -d --force-recreate` 使新配置生效，会重置模拟器内存状态。
