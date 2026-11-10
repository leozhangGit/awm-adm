FROM node:22.16.0-bookworm-slim@sha256:048ed02c5fd52e86fda6fbd2f6a76cf0d4492fd6c6fee9e2c463ed5108da0e34 AS console
WORKDIR /build/console
COPY console/package.json console/package-lock.json ./
RUN npm ci --ignore-scripts
COPY console/ ./
COPY tests/fixtures/v1/models/ /build/tests/fixtures/v1/models/
RUN npm run format:check && npm test && npm run build

FROM ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 AS uv
FROM python:3.13.2-slim-bookworm@sha256:6b3223eb4d93718828223966ad316909c39813dee3ee9395204940500792b740 AS dependencies
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON_DOWNLOADS=never
WORKDIR /build
COPY pyproject.toml uv.lock README.md LICENSE THIRD_PARTY_NOTICES.md ./
COPY src/ src/
RUN uv sync --locked --no-dev --no-editable

FROM python:3.13.2-slim-bookworm@sha256:6b3223eb4d93718828223966ad316909c39813dee3ee9395204940500792b740 AS lean
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends zstd ca-certificates && rm -rf /var/lib/apt/lists/*
COPY deploy/lean-lock.json deploy/fetch_lean.py /build/
RUN python /build/fetch_lean.py /build/lean-lock.json "$TARGETARCH"

FROM python:3.13.2-slim-bookworm@sha256:6b3223eb4d93718828223966ad316909c39813dee3ee9395204940500792b740 AS base
ENV PATH=/opt/venv/bin:/usr/local/bin:/usr/bin:/bin PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY --from=dependencies /opt/venv /opt/venv
RUN /usr/sbin/groupadd --gid 10001 awmadm && /usr/sbin/useradd --uid 10001 --gid 10001 --no-create-home awmadm && mkdir -p /var/lib/awm-adm /var/lib/awm-gateway && chown 10001:10001 /var/lib/awm-adm /var/lib/awm-gateway
WORKDIR /opt/awm-adm
COPY deploy/config.toml /opt/awm-adm/config.toml
USER 10001:10001

FROM base AS worker
CMD ["python", "-m", "awm_adm.runtime.component", "worker"]

FROM base AS gateway
CMD ["python", "-m", "awm_adm.runtime.component", "gateway"]

FROM base AS app
COPY --from=lean /opt/lean /opt/lean
COPY --from=console /build/console/dist /opt/awm-adm/console
ENV AWM_ADM_LEAN=/opt/lean/bin/lean
CMD ["python", "-m", "awm_adm.runtime.server"]

FROM dependencies AS test-dependencies
RUN uv sync --locked --no-editable

FROM app AS test
COPY --from=test-dependencies /opt/venv /opt/venv
COPY --chown=10001:10001 tests/ /opt/awm-adm/tests/
COPY scripts/ /opt/awm-adm/scripts/
COPY examples/ /opt/awm-adm/examples/
COPY contracts/ /opt/awm-adm/contracts/
COPY docs/ /opt/awm-adm/docs/
COPY config/ /opt/awm-adm/config/
COPY src/ /opt/awm-adm/src/
COPY console/ /opt/awm-adm/console-source/
COPY console/package.json console/package-lock.json /opt/awm-adm/console/
COPY pyproject.toml uv.lock README.md LICENSE THIRD_PARTY_NOTICES.md CONTRIBUTING.md SECURITY.md CHANGELOG.md AGENTS.md /opt/awm-adm/
CMD ["python", "-I", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
