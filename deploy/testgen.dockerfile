ARG TESTGEN_BASE_LABEL=v1

FROM datakitchen/dataops-testgen-base:${TESTGEN_BASE_LABEL} AS build-image

# Temporariily adding back the musl-dev lib to allow pip to compile lz4, a Databricks connector dependency. This can
# be removed after the base image is updated with the latest added python dependencies.
RUN apk add musl-dev

# Now install everything
COPY . /tmp/dk/
RUN python3 -m pip install --prefix=/dk /tmp/dk

# The temporary musl-dev lib is no longer neded after this point.
RUN apk del musl-dev

FROM python:3.12.7-alpine3.20 AS release-image

# Args have to be set in current build stage: https://github.com/moby/moby/issues/37345
ARG TESTGEN_VERSION
ARG TESTGEN_DOCKER_HUB_REPO

RUN addgroup -S testgen && adduser -S testgen -G testgen

COPY --from=build-image --chown=testgen:testgen /dk/ /dk
COPY --from=build-image /usr/local/lib/ /usr/local/lib
COPY --from=build-image /usr/lib/ /usr/lib
COPY --from=build-image /opt/microsoft/ /opt/microsoft
COPY --from=build-image /etc/odbcinst.ini /etc/odbcinst.ini

# The OpenSSL upgrade is not carried from the build image, so we have to upgrade it again
#RUN apk add --no-cache openssl=3.3.2-r1

ENV PYTHONPATH=/dk/lib/python3.12/site-packages
ENV PATH="$PATH:/dk/bin:/opt/mssql-tools/bin/"

ENV TESTGEN_VERSION=${TESTGEN_VERSION}
ENV TG_RELEASE_CHECK=docker
ENV TESTGEN_DOCKER_HUB_REPO=${TESTGEN_DOCKER_HUB_REPO}
ENV STREAMLIT_SERVER_MAX_UPLOAD_SIZE=200

RUN mkdir /var/lib/testgen && chown testgen:testgen /var/lib/testgen

USER testgen

WORKDIR /dk

ENTRYPOINT ["testgen"]
CMD [ "ui", "run" ]
