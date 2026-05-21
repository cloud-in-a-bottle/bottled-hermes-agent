FROM ghcr.io/astral-sh/uv:0.11.6-python3.13-trixie AS uv_source

FROM debian:13.4

ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/hermes/.playwright
ENV HERMES_HOME=/opt/data

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential curl python3 python3-dev \
    ripgrep ffmpeg gcc libffi-dev procps git openssh-client \
    tini ca-certificates && \
    rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

COPY --chmod=0755 --from=uv_source /usr/local/bin/uv /usr/local/bin/uvx /usr/local/bin/

WORKDIR /opt/hermes

RUN uv venv /opt/hermes/.venv --python 3.13
ENV PATH="/opt/hermes/.venv/bin:$PATH"
ENV VIRTUAL_ENV="/opt/hermes/.venv"

RUN git clone --depth 1 https://github.com/NousResearch/hermes-agent.git /opt/hermes/repo
WORKDIR /opt/hermes/repo
RUN uv pip install -e '.[all]'
RUN npm install --prefix /opt/hermes/repo
RUN npm install --prefix /opt/hermes/repo/ui-tui
RUN cd /opt/hermes/repo/ui-tui && npm run build || true
RUN npm install --prefix /opt/hermes/repo/web
RUN cd /opt/hermes/repo/web && npm run build || true
WORKDIR /opt/hermes

COPY start.sh /opt/openhost-hermes/start.sh
COPY auth_proxy.py /opt/openhost-hermes/auth_proxy.py

RUN chmod +x /opt/openhost-hermes/start.sh

EXPOSE 8080

CMD ["/opt/openhost-hermes/start.sh"]
