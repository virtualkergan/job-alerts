FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

# tzdata: supercronic reads system zoneinfo to honor TZ.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl tzdata \
 && rm -rf /var/lib/apt/lists/*

# supercronic: a cron built for containers (passes env to jobs, logs to stdout).
# Releases: https://github.com/aptible/supercronic/releases
ARG SUPERCRONIC_VERSION=v0.2.49
ARG TARGETARCH
RUN case "${TARGETARCH:-amd64}" in \
      amd64) SHA256=a53ae236602c7338aba3fbaff40bda6300eae3b9fedb8261eb06cfe3724430c1 ;; \
      arm64) SHA256=02aa0cb229ba09050cba6638059dadb9eedc2276632ea43d6a57a2f8c1629dd5 ;; \
      *) echo "unsupported arch: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
 && curl -fsSLo /usr/local/bin/supercronic \
      "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${TARGETARCH:-amd64}" \
 && echo "${SHA256}  /usr/local/bin/supercronic" | sha256sum -c - \
 && chmod +x /usr/local/bin/supercronic

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py test_connectors.py ./
COPY connectors/ connectors/
# companies.yaml and state.json are bind-mounted by compose.yaml.
