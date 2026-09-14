FROM python:3.13-alpine3.23

ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONFAULTHANDLER=1
ENV ACCEPT_EULA=Y

COPY --chmod=775 ./deploy/install_linuxodbc.sh /tmp/dk/install_linuxodbc.sh

# Install TestGen's main project empty pyproject.toml to install (and cache) the dependencies first
COPY ./pyproject.toml /tmp/dk/pyproject.toml

# The toolchain install, the wheel builds and the `apk del` have to stay in this one RUN. A layer is
# immutable once committed, so deleting the packages from a later layer only writes whiteouts over
# them: they are gone from the running container but still download on every pull. Splitting this
# up costs ~165 MB (amd64) / ~139 MB (arm64) of pulled bytes.
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
        # DuckDB has no musllinux wheel, so it is compiled from its sdist by the install below, and
        # both it and its extensions link against libstdc++ at runtime. Naming it here keeps the
        # apk del below from removing it along with g++
        libstdc++ \
        # Allocator preloaded over musl's at the end of this file. It is a runtime dependency, so
        # it has to stay out of the apk del list below
        mimalloc2 \
        # Additional libraries needed and their dev counterparts. We add both so that we can remove
        # the *-dev later, keeping the libraries
        openblas=0.3.30-r2 \
        openblas-dev=0.3.30-r2 \
        unixodbc=2.3.14-r0 \
        unixodbc-dev=2.3.14-r0 \
    && /tmp/dk/install_linuxodbc.sh \
    && mkdir /dk \
    # Upgrading pip for security
    && python3 -m pip install --no-cache-dir --upgrade pip==26.2.1 \
    # hdbcli only ships manylinux wheels (no musl). pip 26+ correctly rejects these on Alpine.
    # We download the wheel for the correct arch, then extract it directly into site-packages
    # (wheels are zip files). gcompat provides the glibc shim needed at runtime.
    && ARCH=$(uname -m) \
    && pip download --platform manylinux2014_${ARCH} --python-version 3.13 --only-binary :all: \
        --no-deps -d /tmp/wheels hdbcli==2.25.31 \
    && python3 -m zipfile -e /tmp/wheels/hdbcli-*.whl /dk/lib/python3.13/site-packages/ \
    # Copy dist-info to system site-packages so pip sees hdbcli as installed during
    # dependency resolution (sqlalchemy-hana transitively depends on hdbcli~=2.10)
    && cp -r /dk/lib/python3.13/site-packages/hdbcli-*.dist-info \
        "$(python3 -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"/ \
    && rm -rf /tmp/wheels \
    # Strip hdbcli from pyproject.toml before installing — it's already extracted above and
    # pip 26+ would fail trying to resolve it from PyPI on musl
    && sed -i '/hdbcli/d' /tmp/dk/pyproject.toml \
    && python3 -m pip install --no-cache-dir --prefix=/dk /tmp/dk \
    && apk del \
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
    # Remove interactive ODBC tools — not needed at runtime, and iusql triggers
    # false-positive secret detection in security scanners (SECRET-3010)
    && rm -f /usr/bin/iusql /usr/bin/isql \
    && rm -rf /root/.cache/pip /tmp/dk/install_linuxodbc.sh

# Loadable extensions are built per DuckDB version and refuse to load against any other, so
# installing them against the engine installed above pins them to it. DuckDB otherwise fetches them
# over the network on first use, which fails in a locked-down container and behind a proxy whose URL
# carries credentials, since DuckDB's http_proxy parser rejects those. Keep this after the toolchain
# removal above, so that the LOAD exercises the library set the image actually ships. DuckDB's
# default extension directory sits under $HOME, which the runtime user does not reliably have.
ENV TG_DUCKDB_EXTENSION_DIRECTORY=/dk/duckdb/extensions
RUN set -e; \
    for extension in httpfs azure aws; do \
        PYTHONPATH=/dk/lib/python3.13/site-packages python3 -c \
            "import duckdb, os, sys; \
             directory = os.environ['TG_DUCKDB_EXTENSION_DIRECTORY']; \
             connection = duckdb.connect(config={'extension_directory': directory}); \
             connection.execute(f'INSTALL {sys.argv[1]}'); \
             connection.execute(f'LOAD {sys.argv[1]}')" \
            "$extension"; \
    done; \
    chmod -R a+rX "$TG_DUCKDB_EXTENSION_DIRECTORY"

# Replaces musl's allocator for every process in the image. Under musl, concurrent allocation
# serializes badly enough to invert DuckDB's parallel scaling: a profiling query gets slower as
# DuckDB is given more threads, and since DuckDB sizes its thread pool from the detected CPU count,
# a larger container is worse than a small one. Measured on one profiling statement over 100M rows
# at 10 threads: 43.5s on musl against 0.7s here and 0.6s on glibc. Build steps deliberately run on
# the stock allocator; this applies from here on. Removing mimalloc2 above breaks every process.
ENV LD_PRELOAD=/usr/lib/libmimalloc.so.2
