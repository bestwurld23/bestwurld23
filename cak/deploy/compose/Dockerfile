# Civic Node container image (x86_64 labs; a Pi uses deploy/pi/ + systemd).
#
# Deliberately plain: one Python process, no build toolchain in the final image,
# no model baked in. Pin the base digest for a release build.
FROM python:3.12-slim-bookworm AS build

WORKDIR /src
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1

# Copy only what the package needs, so a documentation change does not
# invalidate the dependency layer.
COPY pyproject.toml README.md ./
COPY node ./node
COPY changelog ./changelog
COPY sms ./sms

RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
 && /opt/venv/bin/pip install .


FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.title="Civic Access Kit — Civic Node" \
      org.opencontainers.image.description="Offline-first civic information. Not a voting machine." \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"

COPY --from=build /opt/venv /opt/venv
# Print templates are read from disk at render time.
COPY print /usr/share/cak/print

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CAK_CONFIG=/etc/cak/node.toml

# Unprivileged, and owns only its own state.
RUN useradd --system --create-home --uid 10001 cak \
 && mkdir -p /var/lib/cak/state \
 && chown -R cak:cak /var/lib/cak

USER cak
WORKDIR /var/lib/cak
VOLUME ["/var/lib/cak/state"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/health').read()"

# Shell form so $CAK_CONFIG expands; there is nothing else in this container to
# signal-proxy for.
CMD cak-node serve --config "$CAK_CONFIG"
