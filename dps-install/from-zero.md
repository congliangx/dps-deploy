# 从空源码到完整 Lab：脚本与手工部署

本页复现完整 Lab，包含缺少硬件时的模拟器和独立基础设施。已有客户集群、真实 BMC、数据库或身份服务按 [组件选择](../README.md) 和 [对接指南](existing-infrastructure.md) 跳过相应新建；此页的 13 Secret/9 工作负载/4 PVC 仅指 Lab 组合。

首次新实例在 [installstep.md](../installstep.md) 选择一条整套脚本、分阶段脚本或逐步手工方式；具体脚本动作、产物及对应原生命令都在各 manual，不必把同一安装重复执行两遍。Lab 脚本的统一参数 [deployment.yaml](../deployment.yaml) 中的 runtime_root 由用户选择：支持绝对路径（如 /srv/dps-lab），或相对该配置文件目录的路径（如 .runtime）；填写 . 可与源码同根，运行目录也可以在源码的上级目录。所有下载/生成输入/data/logs/reports/archive 写入 DPS_RUNTIME_ROOT 并排除 Git。源码根由实际 clone 位置推导；L20-12 当前使用 /raid/vince/deploy 与 /raid/vince/deployed-test，是本实例的目录安排。

## 原生步骤与输出

| 顺序 | 命令/动作 | 详细手册 | 预期 |
| --- | --- | --- | --- |
| 1 | apt / curl / sha256sum / docker pull/build | [前置](manual-prerequisites.md) | 官方固定chart/digests/17deb、工具、LDAP2.6.10 |
| 2 | K3s原生systemd / kubectl / docker save / k3s ctr | [前置](manual-prerequisites.md) | 物理节点Ready、local-path/Traefik |
| 3 | openssl / JSON模板 / nginx / docker compose | [BMC](../hardware-sim/manual-install.md) | 新CA/PW，4rack72BMC |
| 4 | openssl / psql CREATE ROLE/4DB / Compose | [PG](manual-postgresql.md) | 独立PG17.11、SCRAM/verify-full |
| 5 | openssl / slappasswd / LDIF/ACL / Compose | [LDAP](manual-ldap.md) | 新真实用户/组/bind、仅LDAPS |
| 6 | openssl / kubectl create secret --from-file | [DPS](manual-install.md) | 新JWT/TLS/13Secrets、无密码values |
| 7 | helm lint/template/upgrade --install | [DPS](manual-install.md) | 9工作负载/4PVC |
| 8 | dpsctl LDAP login/device/topology/settings | [DPS](manual-install.md) | 72AgentId、inactive、PRS=true |

源码提供固定下载来源和公开模板，能够生成全新的安装身份与数据，不依赖L20-12旧密码、CA、旧tar/SHA或旧LDAPimageID。source/env仅解析deployment.yaml；配置渲染内联代码及所有原生命令都在手册完整展示。

## 首次安装与已有实例不同

新实例先确认数据目录空、容器/端口/Docker子网/namespace/release/Ingress域名未被其他实例占用。Kubernetes直接安装于物理OS，BMC/PG/LDAP独立Docker服务；不创建容器模拟节点。

已有实例保留密码/CA/JWT/Secret、LDAP data.mdb、PGDATA、PVC。跳过身份生成与初始化，使用原values做必要维护；日常查询不要运行install/upgrade。官方API拓扑更新使用当前hash、forceUpdate=false，不删除重建/激活。旧LDAP认证迁移不是新装前置。

复用现有原生K3s时，使用现有管理员kubeconfig对应context，并在deployment.yaml选择新的namespace/release/prefix/AgentId/域名/端口/子网/runtime_root。API/UI域名已被另一安装路由占用时拒绝部署。默认物理首次分支与显式集群复用分支的操作在installstep中分开。

默认拓扑inactive，PRS开启但0活跃ResourceGroup/domain；不写BMC功率。mockbackend自行生成TLS，nginx外部leaf由新的项目CA签发；私有backend proxy_ssl_verify off与外部strictCA分别说明，不能声称backend使用项目leaf/key。

## 已执行的验证范围

2026-10-12（Asia/Shanghai）已在空源码副本生成全新密码/CA/JWT/13Secrets与新数据，独立PG33/33、LDAP24/24，全栈44/44（10:25:25+08），9工作负载Ready/0restart、4Docker服务、72BMC strictCA/288GPU144CPU、Controller真实LDAP/TLS、PRS两Pod PGverify-full、S3签名读写/匿名拒绝、CLI/UI会话正负及原始72AgentId/inactive通过。UI通过session API检查，未做浏览器视觉验收。

该轮显式复用L20-12既有物理原生K3s，没有另一台空白OS/K3s首次安装实测。完整入口重入于10:28:56+08退出0；46份证书/密钥/凭据/Secret文件内容不变，数据库sentinel保留后清理。证据在runtime/verification/reports及runtime/verification/archive，日期与完整记录见 [operation-history](../docs/operation-history.md)。

自动化与维护实现索引在 [scripts/README.md](scripts/README.md)，执行示例集中在 installstep，动作展开在 manual。所有安装后验证材料与生产输入分离，安装不会读取verification报告。
