# syntax=docker/dockerfile:1.7

FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend

ARG NPM_REGISTRY=https://registry.npmmirror.com
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm,sharing=locked \
    npm config set registry "${NPM_REGISTRY}" && \
    npm ci --silent

COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim-bookworm
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

ARG DEBIAN_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
ARG DEBIAN_SECURITY_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian-security
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG INSTALL_BROWSER_DEPS=1

RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i \
        -e "s|http://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
        -e "s|https://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
        -e "s|http://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
        -e "s|https://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
        -e "s|http://security.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
        -e "s|https://security.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
        /etc/apt/sources.list.d/debian.sources; \
      rm -f /etc/apt/sources.list; \
    else \
      printf 'deb %s bookworm main\n' "${DEBIAN_MIRROR}" > /etc/apt/sources.list; \
      printf 'deb %s bookworm-updates main\n' "${DEBIAN_MIRROR}" >> /etc/apt/sources.list; \
      printf 'deb %s bookworm-security main\n' "${DEBIAN_SECURITY_MIRROR}" >> /etc/apt/sources.list; \
    fi

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    set -eux; \
    apt-get update \
      -o Acquire::Retries=3 \
      -o Acquire::http::Timeout=30 \
      -o Acquire::https::Timeout=30 \
      -o Acquire::ForceIPv4=true; \
    apt-get install -y --no-install-recommends \
      -o Acquire::Retries=3 \
      -o Acquire::http::Timeout=30 \
      -o Acquire::https::Timeout=30 \
      -o Acquire::ForceIPv4=true \
      ca-certificates \
      curl \
      tzdata; \
    if [ "${INSTALL_BROWSER_DEPS}" = "1" ]; then \
      apt-get install -y --no-install-recommends \
        -o Acquire::Retries=3 \
        -o Acquire::http::Timeout=30 \
        -o Acquire::https::Timeout=30 \
        -o Acquire::ForceIPv4=true \
        chromium \
        dbus \
        dbus-x11 \
        xvfb \
        xauth \
        fonts-liberation \
        fonts-noto-cjk; \
    fi; \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime; \
    echo $TZ > /etc/timezone

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    set -eux; \
    pip install -r requirements.txt --index-url "${PIP_INDEX_URL}"

COPY core ./core
COPY util ./util
COPY main.py .

COPY --from=frontend-builder /app/static ./static

RUN mkdir -p ./data && rm -rf /tmp/* /var/tmp/*

COPY entrypoint.sh .
RUN sed -i 's/\r$//' entrypoint.sh && chmod +x entrypoint.sh

EXPOSE 7860

CMD ["./entrypoint.sh"]
