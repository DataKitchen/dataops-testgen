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
RUN python3 -m pip install --upgrade pip==25.3

RUN python3 -m pip install --prefix=/dk /tmp/dk

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

RUN rm /tmp/dk/install_linuxodbc.sh
