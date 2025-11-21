FROM python:3.12-alpine3.22

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
    linux-headers=6.14.2-r0 \
    # Tools needed for installing the MSSQL ODBC drivers \
    curl \
    gpg \
    # Additional libraries needed and their dev counterparts. We add both so that we can remove
    # the *-dev later, keeping the libraries
    openblas=0.3.28-r0 \
    openblas-dev=0.3.28-r0 \
    unixodbc=2.3.12-r0 \
    unixodbc-dev=2.3.12-r0 \
    # Pinned versions for security
    xz=5.8.1-r0

RUN apk add --no-cache \
    --repository https://dl-cdn.alpinelinux.org/alpine/v3.21/community \
    --repository https://dl-cdn.alpinelinux.org/alpine/v3.21/main \
    libarrow=18.1.0-r0 \
    apache-arrow-dev=18.1.0-r0

COPY --chmod=775 ./deploy/install_linuxodbc.sh /tmp/dk/install_linuxodbc.sh
RUN /tmp/dk/install_linuxodbc.sh

# Install TestGen's main project empty pyproject.toml to install (and cache) the dependencies first
COPY ./pyproject.toml /tmp/dk/pyproject.toml
RUN mkdir /dk
RUN python3 -m pip install --prefix=/dk /tmp/dk

RUN apk del \
    gcc \
    g++ \
    make \
    cmake \
    musl-dev \
    gfortran \
    gpg \
    linux-headers \
    openblas-dev \
    unixodbc-dev \
    apache-arrow-dev

RUN rm /tmp/dk/install_linuxodbc.sh
