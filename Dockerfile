FROM python:3.10-slim-bookworm AS build-image

RUN mkdir -p /dk && \
    apt-get update && \
    apt-get install -y gcc libpcre3 libpcre3-dev g++ git

COPY ./pyproject.toml /tmp/dk/
RUN python3 -m pip install /tmp/dk --prefix=/dk

FROM python:3.10-slim-bookworm AS release-image

RUN apt-get update && \
    apt-get install -y curl gnupg2 && \
    curl -sS https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg && \
    curl -sS https://packages.microsoft.com/config/debian/12/prod.list > /etc/apt/sources.list.d/mssql-release.list && \
    echo msodbcsql18 msodbcsql/ACCEPT_EULA boolean true | debconf-set-selections && \
    mkdir -p /tmp/dk && \
    apt-get update &&  \
    DEBIAN_FRONTEND="noninteractive" ACCEPT_EULA=Y apt-get install -y msodbcsql18 && \
    apt-get remove -y curl gnupg2 && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

COPY . /tmp/dk/
COPY --from=build-image /dk /dk

RUN python3 -m pip install --no-deps /tmp/dk --prefix=/dk
ENV PYTHONPATH ${PYTHONPATH}:/dk/lib/python3.10/site-packages
ENV PATH="$PATH:/dk/bin:/opt/mssql-tools/bin/"

ARG TESTGEN_VERSION
ENV TESTGEN_VERSION=v$TESTGEN_VERSION
ENV TG_RELEASE_CHECK=docker

ENV STREAMLIT_SERVER_MAX_UPLOAD_SIZE=200

WORKDIR /dk

ENTRYPOINT ["testgen"]
CMD [ "ui", "run" ]
