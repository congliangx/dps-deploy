# 手工部署独立 PostgreSQL 17.11

先读取源码 deployment.yaml 导出的环境，完成 [下载镜像与工具](manual-prerequisites.md)。此步骤仅创建新的空数据目录；已有 PGDATA、证书或密码时跳过“生成/初始化”，先核对原配置，不能给已有数据库换密码或重新运行初始化 SQL。

## 1. 生成管理员/应用密码和独立 CA

~~~bash
pg_cfg="$DPS_RUNTIME_ROOT/dps-install/config/postgresql"
pg_data="$DPS_RUNTIME_ROOT/dps-install/data/postgresql"
test ! -e "$pg_cfg/secrets/dps-password"
test ! -e "$pg_data/pgdata/PG_VERSION"
mkdir -p "$pg_cfg/private" "$pg_cfg/tls" "$pg_cfg/secrets" "$pg_data"
chmod 700 "$pg_cfg" "$pg_cfg/private" "$pg_cfg/secrets" "$pg_data"
openssl rand -hex 36 | tr -d '\n' > "$pg_cfg/secrets/admin-password"
openssl rand -hex 36 | tr -d '\n' > "$pg_cfg/secrets/dps-password"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$pg_cfg/private/ca.key"
openssl req -new -x509 -sha256 -days 3650 -key "$pg_cfg/private/ca.key" \
  -out "$pg_cfg/tls/ca.crt" -subj "/CN=DPS PostgreSQL Lab CA" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$pg_cfg/tls/server.key"
openssl req -new -key "$pg_cfg/tls/server.key" -out "$pg_cfg/tls/server.csr" \
  -subj "/CN=$DPS_HOST_NAME"
cat > "$pg_cfg/tls/server.ext" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=IP:$DPS_HOST_IP,DNS:$DPS_HOST_NAME,DNS:localhost,IP:127.0.0.1
EOF
openssl x509 -req -in "$pg_cfg/tls/server.csr" -CA "$pg_cfg/tls/ca.crt" \
  -CAkey "$pg_cfg/private/ca.key" -CAcreateserial -days 825 -sha256 \
  -extfile "$pg_cfg/tls/server.ext" -out "$pg_cfg/tls/server.crt"
openssl verify -CAfile "$pg_cfg/tls/ca.crt" -verify_ip "$DPS_HOST_IP" "$pg_cfg/tls/server.crt"
cp "$pg_cfg/tls/ca.crt" "$DPS_RUNTIME_ROOT/dps-install/config/postgresql-ca.crt"
chmod 755 "$pg_cfg/tls"
chmod 644 "$pg_cfg/tls/ca.crt" "$pg_cfg/tls/server.crt" \
  "$DPS_RUNTIME_ROOT/dps-install/config/postgresql-ca.crt"
chmod 600 "$pg_cfg/private/ca.key" "$pg_cfg/tls/server.key" "$pg_cfg/secrets/"*
chown 999:999 "$pg_cfg/tls/server.key" "$pg_cfg/secrets/"* "$pg_data"
~~~

预期证书 verify 为 OK；CA 签名私钥不挂到 PG 容器。官方 postgres:17 固定镜像实际 UID/GID 999。管理员 postgres 与应用 dps 使用两个独立随机密码；密码只能保存在 600 文件。

将必要连接信息保存为私密 JSON，供安全登录/维护读取，过程不输出值：

~~~bash
python3 - <<'PY'
import json,os
from pathlib import Path
root=Path(os.environ["DPS_RUNTIME_ROOT"]); c=root/"dps-install/config"
p=c/"postgresql/secrets"
x={"host":os.environ["DPS_HOST_IP"],"port":int(os.environ["DPS_PG_PORT"]),
   "database":"dps","username":"dps","password":(p/"dps-password").read_text(),
   "admin_username":"postgres","admin_password":(p/"admin-password").read_text(),
   "sslmode":"verify-full","sslrootcert":str(c/"postgresql-ca.crt"),
   "secret_name":"dps-postgresql","secret_key":"password"}
(c/"postgresql-credentials.json").write_text(json.dumps(x,indent=2)+"\n")
(c/"postgresql-credentials.json").chmod(0o600)
PY
~~~

## 2. 配置 SCRAM、TLS 和允许来源

~~~bash
cat > "$pg_cfg/postgresql.conf" <<'EOF'
listen_addresses = '*'
port = 5432
max_connections = 200
shared_buffers = '256MB'
password_encryption = 'scram-sha-256'
hba_file = '/etc/postgresql/config/pg_hba.conf'
ssl = on
ssl_cert_file = '/etc/postgresql/tls/server.crt'
ssl_key_file = '/etc/postgresql/tls/server.key'
ssl_ca_file = '/etc/postgresql/tls/ca.crt'
ssl_min_protocol_version = 'TLSv1.2'
log_connections = on
log_disconnections = on
log_statement = 'none'
log_min_error_statement = 'panic'
EOF
cat > "$pg_cfg/pg_hba.conf" <<EOF
local all postgres peer
local all all scram-sha-256
hostnossl all all 0.0.0.0/0 reject
hostnossl all all ::/0 reject
hostssl dps,dps_prs_config,dps_prs_config_staged,dps_prs_controller dps $DPS_HOST_IP/32 scram-sha-256
hostssl dps,dps_prs_config,dps_prs_config_staged,dps_prs_controller dps $DPS_POD_CIDR scram-sha-256
hostssl dps,dps_prs_config,dps_prs_config_staged,dps_prs_controller dps $DPS_PG_SUBNET scram-sha-256
host all all 0.0.0.0/0 reject
host all all ::/0 reject
EOF
chmod 644 "$pg_cfg/postgresql.conf" "$pg_cfg/pg_hba.conf"
~~~

仅允许配置中的宿主机、Pod CIDR 和独立 PG bridge 网段，经 TLS/SCRAM 使用 dps 角色连接四库。明文和其他来源拒绝。server CA/SAN 与应用 verify-full 一起验证服务器身份；没有使用宽泛的 trust。

## 3. 声明角色、四库和迁移权限

此 SQL 仅由官方镜像在空 PGDATA 首次执行。psql 从私密挂载文件读取应用密码，不把密码写入 SQL 或 argv。

~~~bash
cat > "$pg_cfg/10-init-dps.sql" <<'SQL'
\set dps_password `cat /run/secrets/dps-password`
CREATE ROLE dps WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'dps_password';
\unset dps_password
CREATE DATABASE dps OWNER dps;
REVOKE ALL ON DATABASE dps FROM PUBLIC;
GRANT CONNECT ON DATABASE dps TO dps;
\connect dps
ALTER SCHEMA public OWNER TO dps;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO dps;
CREATE DATABASE dps_prs_config OWNER dps;
REVOKE ALL ON DATABASE dps_prs_config FROM PUBLIC;
GRANT CONNECT ON DATABASE dps_prs_config TO dps;
\connect dps_prs_config
ALTER SCHEMA public OWNER TO dps;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO dps;
CREATE DATABASE dps_prs_config_staged OWNER dps;
REVOKE ALL ON DATABASE dps_prs_config_staged FROM PUBLIC;
GRANT CONNECT ON DATABASE dps_prs_config_staged TO dps;
\connect dps_prs_config_staged
ALTER SCHEMA public OWNER TO dps;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO dps;
CREATE DATABASE dps_prs_controller OWNER dps;
REVOKE ALL ON DATABASE dps_prs_controller FROM PUBLIC;
GRANT CONNECT ON DATABASE dps_prs_controller TO dps;
\connect dps_prs_controller
ALTER SCHEMA public OWNER TO dps;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO dps;
SQL
chmod 644 "$pg_cfg/10-init-dps.sql"
~~~

应用用户无 superuser/createdb/createrole 权限。四库分别供 DPS Core、PRS Config、staged Config、Controller 使用；Owner dps 并拥有 public schema 的迁移权限。

## 4. 写 Compose 并启动

~~~bash
cat > "$pg_cfg/compose.yaml" <<EOF
services:
  postgresql:
    image: postgres@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3
    container_name: $DPS_PG_CONTAINER
    restart: unless-stopped
    shm_size: 512m
    environment:
      POSTGRES_USER: postgres
      POSTGRES_DB: postgres
      POSTGRES_PASSWORD_FILE: /run/secrets/admin-password
      POSTGRES_INITDB_ARGS: --auth-local=peer --auth-host=scram-sha-256
      PGDATA: /var/lib/postgresql/data/pgdata
    command: [postgres, -c, config_file=/etc/postgresql/config/postgresql.conf]
    ports: ["$DPS_HOST_IP:$DPS_PG_PORT:5432"]
    volumes:
      - $pg_data:/var/lib/postgresql/data
      - $pg_cfg/postgresql.conf:/etc/postgresql/config/postgresql.conf:ro
      - $pg_cfg/pg_hba.conf:/etc/postgresql/config/pg_hba.conf:ro
      - $pg_cfg/tls:/etc/postgresql/tls:ro
      - $pg_cfg/secrets/admin-password:/run/secrets/admin-password:ro
      - $pg_cfg/secrets/dps-password:/run/secrets/dps-password:ro
      - $pg_cfg/10-init-dps.sql:/docker-entrypoint-initdb.d/10-init-dps.sql:ro
    healthcheck:
      test: [CMD-SHELL, pg_isready -U postgres -d postgres]
      interval: 5s
      timeout: 5s
      retries: 20
      start_period: 15s
    logging:
      driver: json-file
      options: {max-size: "10m", max-file: "3"}
    networks: [database]
networks:
  database:
    name: $DPS_PG_NETWORK
    ipam:
      config: [{subnet: "$DPS_PG_SUBNET"}]
EOF
docker compose -p "$DPS_PG_PROJECT" -f "$pg_cfg/compose.yaml" config --quiet
docker compose -p "$DPS_PG_PROJECT" -f "$pg_cfg/compose.yaml" up -d --wait
docker compose -p "$DPS_PG_PROJECT" -f "$pg_cfg/compose.yaml" ps
docker exec -u postgres "$DPS_PG_CONTAINER" psql -d postgres -Atc \
  "select datname,pg_get_userbyid(datdba) from pg_database where datname like 'dps%';"
~~~

预期 healthy，四库均 Owner dps，server 17.11。初始化只运行一次；保留 data/pgdata/PG_VERSION。后续 up 不会重建数据库。严禁 docker compose down -v 或删除 runtime 数据作为重入步骤。

## 5. 严格 TLS 登录和备份

生成 600 pgpass 文件，再使用本机 psql 客户端容器经 host 网络连接。密码文件不进入 argv，TLS 需要 CA 与正确 IP/SAN。

~~~bash
python3 - <<'PY'
import os
from pathlib import Path
c=Path(os.environ["DPS_RUNTIME_ROOT"])/"dps-install/config/postgresql"
password=(c/"secrets/dps-password").read_text()
(c/"secrets/pgpass").write_text(
 f'{os.environ["DPS_HOST_IP"]}:{os.environ["DPS_PG_PORT"]}:*:dps:{password}\n')
(c/"secrets/pgpass").chmod(0o600)
PY
docker run --rm --network host \
  -e PGSSLMODE=verify-full -e PGSSLROOTCERT=/ca.crt -e PGPASSFILE=/pgpass \
  -v "$pg_cfg/tls/ca.crt:/ca.crt:ro" -v "$pg_cfg/secrets/pgpass:/pgpass:ro" \
  postgres@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3 \
  psql -h "$DPS_HOST_IP" -p "$DPS_PG_PORT" -U dps -d dps -Atc \
  "select current_user, ssl, version from pg_stat_ssl where pid=pg_backend_pid();"
backup_dir="$DPS_RUNTIME_ROOT/dps-install/data/postgresql-backups"
mkdir -p "$backup_dir"
backup_stamp=$(date -u +%Y%m%dT%H%M%SZ)
for database in dps dps_prs_config dps_prs_config_staged dps_prs_controller; do
  docker exec -u postgres "$DPS_PG_CONTAINER" pg_dump -Fc "$database" \
    > "$backup_dir/$database-$backup_stamp.dump"
  chmod 600 "$backup_dir/$database-$backup_stamp.dump"
  docker exec -i -u postgres "$DPS_PG_CONTAINER" pg_restore --list \
    < "$backup_dir/$database-$backup_stamp.dump" > /dev/null
done
~~~

预期 current_user=dps、ssl=t、TLSv1.2/1.3，四份 custom dump catalog 可读。备份校验不是向生产库恢复。DPS/PRS 实际 Pod TLS 检查见 verification；安装后再次备份，因为 schema 在 Helm migrations 后发生变化。下一步 [独立 LDAP](manual-ldap.md)，13 个 Kubernetes Secret 在 [DPS 手工安装](manual-install.md) 中统一创建。
