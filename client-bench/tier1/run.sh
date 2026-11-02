#!/usr/bin/env bash
# Run the Tier-1 client bench end to end (CASE-MATRIX.md, amendment of 2 November 2026).
#
# One loopback server container, then one container per SDK sharing its network namespace,
# so every flow talks to 127.0.0.1 and nothing leaves the host except package downloads.
# Every container is limited to two CPUs. Raw request logs land in raw/, and score.py turns
# them into results.jsonl. Images are pinned by tag and their digests written to
# raw/images.txt.
#
#   ./run.sh            # from this directory; Docker must be running
#
# On Windows under Git Bash, run with MSYS_NO_PATHCONV=1 and BENCH_DIR set to the Windows
# path of this directory.
set -euo pipefail

B="${BENCH_DIR:-$(pwd)}"
NODE=node:24.21.0-trixie
PYTHON=python:3.13-trixie
DOTNET=mcr.microsoft.com/dotnet/sdk:10.0.401-resolute
GO=golang:1.27.1-trixie
RUST=rust:1.98.1-trixie
RUBY=ruby:3.4.11-trixie
LIMIT=(--cpus=2)
NET=(--network container:bench-fake)

mkdir -p raw
for image in "$NODE" "$PYTHON" "$DOTNET" "$GO" "$RUST" "$RUBY"; do
  echo "$image $(docker image inspect --format '{{index .RepoDigests 0}}' "$image" 2>/dev/null || echo unpulled)"
done > raw/images.txt

docker rm -f bench-fake >/dev/null 2>&1 || true
docker run -d --rm --name bench-fake --cpus=0.5 -v "$B/fake:/f:ro" "$NODE" node /f/server.mjs >/dev/null
trap 'docker rm -f bench-fake >/dev/null 2>&1 || true' EXIT
sleep 2

# TypeScript: both lines, versions pinned in ts/package.json and ts/package-lock.json.
docker run --rm "${LIMIT[@]}" "${NET[@]}" -v "$B/ts:/w" -v "$B/raw:/out" -w /w "$NODE" \
  sh -c 'test -d node_modules || npm ci --no-audit --no-fund --ignore-scripts >/dev/null; node driver.mjs > /out/ts.jsonl 2> /out/ts.stderr'

# Python: mcp 2.3.0 installed into python/site.
docker run --rm "${LIMIT[@]}" "${NET[@]}" -e PYTHONPATH=/w/site -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$B/python:/w" -v "$B/raw:/out" -w /w "$PYTHON" \
  sh -c 'test -d site/mcp || pip install --quiet --disable-pip-version-check --target /w/site mcp==2.3.0; python driver.py > /out/python.jsonl 2> /out/python.stderr'

# C#: ModelContextProtocol 2.3.0, telemetry off.
docker run --rm "${LIMIT[@]}" "${NET[@]}" -e DOTNET_CLI_TELEMETRY_OPTOUT=1 -e DOTNET_NOLOGO=1 \
  -e NUGET_PACKAGES=/w/.nuget -v "$B/csharp:/w" -v "$B/raw:/out" -w /w "$DOTNET" \
  sh -c 'dotnet build -c Release -o /w/out >/dev/null && dotnet /w/out/bench.dll > /out/csharp.jsonl 2> /out/csharp.stderr'

# Go: go-sdk v1.8.0, pinned in go/go.mod and go/go.sum.
docker run --rm "${LIMIT[@]}" "${NET[@]}" -e GOPATH=/w/.gopath -e GOCACHE=/w/.gocache \
  -e GOFLAGS=-modcacherw -e GOTOOLCHAIN=local -v "$B/go:/w" -v "$B/raw:/out" -w /w "$GO" \
  sh -c 'go build -o /w/bench . && ./bench > /out/go.jsonl 2> /out/go.stderr'

# Rust: rmcp 3.8.0, pinned in rust/Cargo.toml and rust/Cargo.lock.
docker run --rm "${LIMIT[@]}" "${NET[@]}" -e CARGO_HOME=/w/.cargo -e CARGO_BUILD_JOBS=2 \
  -v "$B/rust:/w" -v "$B/raw:/out" -w /w "$RUST" \
  sh -c 'cargo build --release --locked -q && ./target/release/bench > /out/rust.jsonl 2> /out/rust.stderr'

# Ruby: mcp 1.8.2 plus the gems its HTTP client and OAuth flow require but do not declare.
docker run --rm "${LIMIT[@]}" "${NET[@]}" -e GEM_HOME=/w/gems -e GEM_PATH=/w/gems \
  -v "$B/ruby:/w" -v "$B/raw:/out" -w /w "$RUBY" \
  sh -c 'test -d gems/gems/mcp-1.8.2 || gem install mcp:1.8.2 faraday:2.15.1 event_stream_parser:1.0.0 base64:0.3.0 --install-dir /w/gems --no-document >/dev/null; ruby driver.rb > /out/ruby.jsonl 2> /out/ruby.stderr'

python3 score.py 2>/dev/null || python score.py
