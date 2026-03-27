FROM python:3.12-alpine3.23

ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONFAULTHANDLER=1
ENV ACCEPT_EULA=Y

RUN apk update && apk upgrade && apk add --no-cache \
    # Tools needed for building the python wheels
    gcc \
    g++ \
    make \
    cmake \
    musl-dev \
    gfortran \
    linux-headers=6.16.12-r0 \
    # Tools needed for installing the MSSQL ODBC drivers
    curl \
    gpg \
    gpgv \
    openssl \
    # glibc compatibility layer for packages that only ship manylinux wheels (e.g. hdbcli)
    gcompat \
    # Additional libraries needed and their dev counterparts. We add both so that we can remove
    # the *-dev later, keeping the libraries
    openblas=0.3.30-r2 \
    openblas-dev=0.3.30-r2 \
    unixodbc=2.3.14-r0 \
    unixodbc-dev=2.3.14-r0 \
    libarrow=21.0.0-r4 \
    apache-arrow-dev=21.0.0-r4 \
    # Pinned versions for security
    xz=5.8.2-r0

COPY --chmod=775 ./deploy/install_linuxodbc.sh /tmp/dk/install_linuxodbc.sh
RUN /tmp/dk/install_linuxodbc.sh

# Install TestGen's main project empty pyproject.toml to install (and cache) the dependencies first
COPY ./pyproject.toml /tmp/dk/pyproject.toml
RUN mkdir /dk

# Upgrading pip for security
RUN python3 -m pip install --no-cache-dir --upgrade pip==26.0

# hdbcli only ships manylinux wheels (no musl). pip 26+ correctly rejects these on Alpine.
# We download the wheel for the correct arch, then extract it directly into site-packages
# (wheels are zip files). gcompat provides the glibc shim needed at runtime.
RUN ARCH=$(uname -m) && \
    pip download --platform manylinux2014_${ARCH} --python-version 3.12 --only-binary :all: \
        --no-deps -d /tmp/wheels hdbcli==2.25.31 && \
    python3 -m zipfile -e /tmp/wheels/hdbcli-*.whl /dk/lib/python3.12/site-packages/ && \
    # Copy dist-info to system site-packages so pip sees hdbcli as installed during
    # dependency resolution (sqlalchemy-hana transitively depends on hdbcli~=2.10)
    cp -r /dk/lib/python3.12/site-packages/hdbcli-*.dist-info \
        "$(python3 -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"/ && \
    rm -rf /tmp/wheels

# Strip hdbcli from pyproject.toml before installing — it's already extracted above and
# pip 26+ would fail trying to resolve it from PyPI on musl
RUN sed -i '/hdbcli/d' /tmp/dk/pyproject.toml

RUN python3 -m pip install --no-cache-dir --prefix=/dk /tmp/dk

RUN apk del \
    gcc \
    g++ \
    make \
    cmake \
    curl \
    musl-dev \
    gfortran \
    gpg \
    gpgv \
    openssl \
    linux-headers \
    openblas-dev \
    unixodbc-dev \
    apache-arrow-dev

RUN rm -rf /root/.cache/pip /tmp/dk/install_linuxodbc.sh
