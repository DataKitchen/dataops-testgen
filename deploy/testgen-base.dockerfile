FROM python:3.12.7-alpine3.20

ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONFAULTHANDLER=1
ENV ACCEPT_EULA=Y

RUN apk update && apk add --no-cache \
    gcc \
    g++ \
    bash \
    libffi-dev \
    openssl-dev \
    cargo \
    musl-dev \
    postgresql-dev \
    cmake \
    rust \
    linux-headers \
    libc-dev \
    libgcc \
    libstdc++ \
    ca-certificates \
    zlib-dev \
    bzip2-dev \
    xz-dev \
    lz4-dev \
    zstd-dev \
    snappy-dev \
    brotli-dev \
    build-base \
    autoconf \
    boost-dev \
    flex \
    libxml2-dev \
    libxslt-dev \
    libjpeg-turbo-dev \
    ninja \
    git \
    curl \
    unixodbc-dev \
    gpg \
    openssl=3.3.2-r1 \
    gfortran \
    openblas-dev

RUN mkdir /dk

COPY --chmod=775 ./deploy/install_linuxodbc.sh /tmp/dk/install_linuxodbc.sh
RUN /tmp/dk/install_linuxodbc.sh

COPY --chmod=775 ./deploy/install_arrow.sh /tmp/dk/install_arrow.sh
RUN /tmp/dk/install_arrow.sh

# Install TestGen's main project empty pyproject.toml to install (and cache) the dependencies first
COPY ./pyproject.toml /tmp/dk/pyproject.toml
RUN python3 -m pip install --prefix=/dk /tmp/dk

RUN apk del \
    gcc \
    g++ \
    bash \
    libffi-dev \
    openssl-dev \
    cargo \
    musl-dev \
    postgresql-dev \
    cmake \
    rust \
    linux-headers \
    libc-dev \
    build-base \
    autoconf \
    boost-dev \
    flex \
    ninja \
    curl \
    unixodbc-dev \
    gpg \
    ca-certificates \
    git
