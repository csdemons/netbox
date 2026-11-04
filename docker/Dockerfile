# Основа — именно версия NetBox Docker, соответствующая инфраструктуре.
ARG NETBOX_IMAGE=docker.io/netboxcommunity/netbox:v4.7
FROM ${NETBOX_IMAGE}

USER root
COPY . /opt/netbox-server-wizard

# Для актуальных образов netbox-docker используется uv; старые могут иметь pip.
RUN if command -v uv >/dev/null 2>&1; then \
      uv pip install --python /opt/netbox/venv/bin/python --no-deps /opt/netbox-server-wizard; \
    else \
      /opt/netbox/venv/bin/python -m pip install --no-deps /opt/netbox-server-wizard; \
    fi \
    && rm -rf /opt/netbox-server-wizard

USER netbox:root
