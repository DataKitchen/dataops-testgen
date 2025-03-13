ARG TESTGEN_BASE_LABEL=v2

FROM datakitchen/dataops-testgen-base:${TESTGEN_BASE_LABEL} AS release-image

# Args have to be set in current build stage: https://github.com/moby/moby/issues/37345
ARG TESTGEN_VERSION
ARG TESTGEN_DOCKER_HUB_REPO

# Now install everything
COPY . /tmp/dk/
RUN python3 -m pip install --prefix=/dk /tmp/dk
RUN rm -Rf /tmp/dk

RUN addgroup -S testgen && adduser -S testgen -G testgen

# Streamlit has to be able to write to these dirs
RUN mkdir /var/lib/testgen
RUN chown -R testgen:testgen /var/lib/testgen /dk/lib/python3.12/site-packages/streamlit/static

ENV PYTHONPATH=/dk/lib/python3.12/site-packages
ENV PATH=$PATH:/dk/bin

ENV TESTGEN_VERSION=${TESTGEN_VERSION}
ENV TG_RELEASE_CHECK=docker
ENV TESTGEN_DOCKER_HUB_REPO=${TESTGEN_DOCKER_HUB_REPO}
ENV STREAMLIT_SERVER_MAX_UPLOAD_SIZE=200

USER testgen

WORKDIR /dk

ENTRYPOINT ["testgen"]
CMD [ "ui", "run" ]
