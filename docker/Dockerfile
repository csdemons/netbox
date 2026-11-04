# Основа — именно версия NetBox Docker, соответствующая инфраструктуре.
ARG NETBOX_IMAGE
FROM ${NETBOX_IMAGE}

USER root
COPY . /opt/netbox-plan

# Для актуальных образов netbox-docker используется uv; старые могут иметь pip.
RUN if command -v uv >/dev/null 2>&1; then \
      uv pip install --python /opt/netbox/venv/bin/python --no-deps /opt/netbox-plan; \
    else \
      /opt/netbox/venv/bin/python -m pip install --no-deps /opt/netbox-plan; \
    fi \
    && rm -rf /opt/netbox-plan

USER netbox:root
