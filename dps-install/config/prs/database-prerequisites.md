# PRS / Power Steering 外部 PostgreSQL 准备

本项目复用独立 PostgreSQL 17.11（容器 dps-postgresql，10.6.131.43:15432）与现有非superuser应用角色 dps。DPS 0.9.0 内嵌的 Power Steering chart 为2.1.0；固定chart初始化SQL只要求创建数据库并授权，没有预创建额外extension的要求。应用服务启动时自行执行migration。

| 用途 | 数据库 | Owner |
| --- | --- | --- |
| Config | dps_prs_config | dps |
| Config staged | dps_prs_config_staged | dps |
| Controller | dps_prs_controller | dps |

原DPS业务数据库 dps 保留，未重置。应用角色仍无superuser、CREATEDB、CREATEROLE权限。三个PRS库撤销PUBLIC数据库权限，并确保dps可使用及创建public schema对象。

## 安装输入与执行

必要SQL为 `prepare-databases.sql`，连接信息与已准备状态为 `databases.json`；均不含密码。密码继续由父chart的现有PostgreSQL Secret提供，不另建数据库超级用户凭据。

```bash
ssh root@L20-12
cd /raid/vince/deploy
python3 dps-install/scripts/prepare-prs-databases.py
```

该脚本先确认现有库Owner；若PRS库已由其他角色持有则拒绝接管。准备前备份现有DPS库及受影响的已有PRS库，幂等创建缺失库、补齐权限，备份并更新PG HBA后仅reload配置，不重启PostgreSQL。它不安装或升级DPS。

HBA文件为 `dps-install/config/postgresql/pg_hba.conf`。PRS只新增限定三个库、角色dps、SCRAM认证的hostssl规则，允许范围与现有DPS相同：

- 宿主机 `10.6.131.43/32`
- 原生K3s Pod `10.42.0.0/16`
- 现有数据库容器网络 `172.30.90.0/24`

明文IPv4/IPv6连接以及其余未匹配来源仍被拒绝。HBA单文件bind mount需要原inode，因此脚本在备份后原位写入、校验pg_hba_file_rules并reload；失败时恢复原文件。

## Power Steering 客户端 TLS

已检查实际 `power-config:2.1.0`、`power-controller:2.1.0` 的Python配置及引擎：均使用SQLAlchemy和psycopg2 2.9.11。DatabaseSettings没有数据库TLS专用字段；实际连接通过libpq读取以下环境变量：

```yaml
extraEnv:
  - name: PGSSLMODE
    value: verify-full
  - name: PGSSLROOTCERT
    value: /secrets/postgresql/ca.crt
```

这两个环境变量应同时加入Power Steering Config和Controller；挂载现有 `dps-postgresql-ca` Secret的CA到对应路径。密码保留现有Secret引用，不放到URL、values或命令行。不能使用未实现的 `DATABASE__TLS_*` 字段代替。[PostgreSQL libpq环境参数](https://www.postgresql.org/docs/17/libpq-envars.html)、[Psycopg连接参数](https://www.psycopg.org/docs/module.html)

实际镜像引擎已验证三库TLSv1.3与DDL/insert/rollback权限；错误CA、错误服务端名称、明文连接、错误密码均被拒绝。报告位于 `verification/reports/prs-databases.json`，脚本为 `verification/scripts/verify-prs-databases.py`，仅用于验证，不被安装脚本读取。该报告的网络探针使用独立应用镜像的host networking；部署后还需检查实际Pod数据库会话与应用migration。

## 备份与恢复

```bash
dps-install/scripts/postgresql-backup.sh
dps-install/scripts/postgresql-backup-prs.sh
```

前者备份现有DPS库，后者分别备份三个PRS库；自定义格式dump保存在 `dps-install/data/postgresql-backups/`，权限600，导出后以pg_restore --list校验。HBA变更前配置亦保存在该目录，具体路径记录在 `databases.json`。

恢复前停止相关应用写入，保留现有数据，创建目标库及正确Owner后使用匹配PostgreSQL17工具恢复custom dump。当前已验证备份可读取，未覆盖恢复正在使用的业务库。
