# syntax=docker/dockerfile:1
# PLVA private reasoning: minimal linux/arm64 (or amd64) image for the OpenShell sandbox.
#
# Build from the REPO ROOT (the context must contain pyproject.toml, README.md, LICENSE, src/):
#   docker build --platform linux/arm64 -f sandbox/Dockerfile -t plva-pr-sandbox:local .
# sandbox/Dockerfile.dockerignore keeps models/, .venv/, reference/ and everything else out of
# the context; the model is NOT baked in. Mount models/ read-only at /models at sandbox
# creation (see sandbox/start.sh, openshell branch).
#
# Stage 1 compiles llama-cpp-python (CPU only; no Metal/CUDA inside a container) and installs
# the package with the `local` extra into a venv. Stage 2 keeps only the venv + libgomp.

FROM python:3.12-slim AS build
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential cmake ninja-build \
 && rm -rf /var/lib/apt/lists/*
RUN python -m venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FORCE_CMAKE=1 \
    CMAKE_ARGS="-DGGML_NATIVE=OFF -DGGML_METAL=OFF -DGGML_CUDA=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_TESTS=OFF" \
    CMAKE_BUILD_PARALLEL_LEVEL=2
# Pinned runtime (matches src/plva_private_reasoning/model/manifest.json "runtime"). This layer
# is the slow one (several minutes on 2 vCPU); it is cached independently of the package below.
RUN pip install --upgrade pip && pip install llama-cpp-python==0.3.35
COPY pyproject.toml README.md LICENSE /src/
COPY src /src/src
RUN pip install "/src[local]"

FROM python:3.12-slim
# libgomp1: OpenMP runtime for llama.cpp. iproute2 + nftables: the OpenShell supervisor
# (0.0.116) needs trusted `ip` and `nft` helpers (/usr/sbin) to build the sandbox's private
# network namespace and its deny/REJECT rules; without `ip` the container exits with
# "Network namespace creation failed and proxy mode requires isolation", without `nft` with
# "trusted nft helper not found; policy DNS and transparent TCP require nftables".
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 iproute2 nftables \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 --user-group sandbox \
 && mkdir -p /models \
 && install -d -o sandbox -g sandbox -m 700 /tmp/plva-pr
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    PLVA_PR_MODEL_PATH=/models/Qwen3-1.7B-Q8_0.gguf \
    PLVA_PR_RUNTIME_DIR=/tmp/plva-pr
# OpenShell refuses an image without an OCI USER unless the policy sets process.run_as_user;
# we set both (policy.yaml: run_as_user: sandbox). Never root inside the boundary.
USER sandbox
# WORKDIR doubles as OpenShell's "image workspace"; the supervisor refuses to start unless it
# is writable by the OCI user, hence the chown above.
WORKDIR /tmp/plva-pr
# No ENTRYPOINT/CMD on purpose: OpenShell supplies the sandbox's main process; start.sh execs
# plva-pr-local explicitly. `plva-pr-local --help` works as a smoke test.
