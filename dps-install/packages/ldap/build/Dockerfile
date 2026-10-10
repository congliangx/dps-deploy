FROM debian@sha256:a29215f6a35e51e22adffa17f89e9d2ef06214e64a2bad10d765c46aea49f11f
ARG DEBIAN_FRONTEND=noninteractive
COPY debs/ /tmp/debs/
RUN printf 'slapd slapd/no_configuration boolean true\n' | debconf-set-selections && \
    apt-get -y --no-install-recommends install /tmp/debs/*.deb && \
    groupadd --gid 10001 ldapdaemon && \
    useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin ldapdaemon && \
    rm -rf /tmp/debs /var/lib/apt/lists/* /var/lib/ldap /etc/ldap/slapd.d && \
    mkdir -p /var/lib/ldap /run/slapd /run/ldap-config && \
    dpkg-query -W > /usr/local/share/installed-packages.tsv
COPY entrypoint.sh /usr/local/bin/ldap-entrypoint
RUN chmod 755 /usr/local/bin/ldap-entrypoint
ENTRYPOINT ["/usr/local/bin/ldap-entrypoint"]
