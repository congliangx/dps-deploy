# 从零搭建完整 Lab

本页说明完整 Lab 脚本的范围和验证边界。具体执行入口在 [installstep.md](../installstep.md)，脚本阶段与逐步原生命令在各 manual。客户已有基础设施按 [组件选择](../README.md) 和 [对接指南](existing-infrastructure.md) 跳过新建。

## 完整 Lab 安装什么

| 阶段 | 内容 | 详细手册 |
| --- | --- | --- |
| 主机与包 | OS 依赖、固定 chart/镜像/工具、OpenLDAP 镜像构建 | [前置要求](manual-prerequisites.md) |
| 物理集群 | 原生 K3s、local-path、Traefik、containerd 镜像导入 | [主机/K3s](manual-prerequisites.md) |
| 模拟硬件 | 4 rack/72 BMC、URL、密码、CA、nginx/Compose | [BMC](../hardware-sim/manual-install.md) |
| 数据库 | 独立 PG、应用角色、Core/PRS 四库、TLS/SCRAM | [PG](manual-postgresql.md) |
| 身份服务 | 独立 LDAP、真实用户/组/只读 bind、LDAPS | [LDAP](manual-ldap.md) |
| DPS / PRS | TLS/JWT/13 Secret、values/Helm、真实登录、72 AgentId inactive 拓扑、PRS=true | [DPS](manual-install.md) |

完整组合为 9 工作负载/4 PVC；客户按需选择的部署不必满足这些数量。脚本与手工安装二选一。独立组件入口不是整套脚本的暂停模式，组件先启动后按 DPS 手册或对接指南继续。

## 新实例与维护

新实例先修改 [deployment.yaml](../deployment.yaml)，确认数据目录空，端口、Compose project、Docker 网段、namespace/release、Ingress 域名未与其他实例冲突。脚本生成新密码、CA、JWT、Secret 和空数据，不依赖 L20-12 旧凭据或旧下载缓存。

显式复用仅接受本仓库支持的本机原生 K3s：固定 v1.34.12+k3s1、/usr/local/bin/k3s server --config 启动，配置 node IP/API 端口/Pod 与 Service CIDR、集群 CA、物理 Node UID 和显式 context 均须匹配。提供管理员 kubeconfig，选择独立 namespace/release、prefix、AgentId、域名、端口、网段和 runtime；操作见 [installstep 的 B 分支](../installstep.md)。其他已有 K3s/Kubernetes 按 [客户对接指南](existing-infrastructure.md) 手工安装 DPS。

已有实例维护保留密码、CA、JWT、Secret、PG/LDAP 数据与 PVC，跳过身份生成和初始化。使用现有 values；日常查询无需 install/upgrade。拓扑更新使用当前 hash、forceUpdate=false，不删除重建或激活。

运行目录由用户选择，可与源码同根、位于源码内部或外部，布局及相对路径规则见 [根 README](../README.md)。下载/生成物和验证报告不提交 Git，也不把验证报告当作安装依赖。

## 模拟与验收边界

拓扑保持 inactive，PRS 开启但无活跃 ResourceGroup/domain；安装不写 BMC 功率。模拟器 backend 自生成 TLS，外部 nginx leaf 由项目 CA 签发。私有 backend 的 proxy_ssl_verify off 与外部严格 CA 校验分别说明，见 [BMC 手册](../hardware-sim/manual-install.md)。

2026-10-12 已在空源码副本、新身份和新数据的隔离实例验证 PG 33/33、LDAP 24/24、全栈 44/44，以及完整入口重入后 46 份身份文件与数据库内容保留。该轮复用了 L20-12 既有物理 K3s，没有另一台空白 OS/K3s 首装实测；UI 使用 session API，未做浏览器视觉验收。

完整范围、时间与证据位置见 [操作历史](../docs/operation-history.md)。结果只代表当轮环境，当前部署变化后需按 [验证指南](../verification/README.md) 复查；真实 GB300 固件、多节点 HA 和动态功率控制尚未验证。

安装/维护脚本见 [scripts/README.md](scripts/README.md)，安装后的访问和维护从 [dps-access.md](dps-access.md) 开始。
