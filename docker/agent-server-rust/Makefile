.PHONY: dev check build release test clean cross-amd64 cross-arm64

# ── Development ──────────────────────────────────────────────

# Type-check on file change (fastest feedback loop)
dev:
	cargo watch -x check

# Type-check + run server on file change
run:
	cargo watch -x run

# One-shot type check (like tsc --noEmit)
check:
	cargo check

# Debug build
build:
	cargo build

# Run tests
test:
	cargo test

# Run tests on file change
test-watch:
	cargo watch -x test

# ── Release ──────────────────────────────────────────────────

# Optimized release build (native platform)
release:
	cargo build --release

# ── Cross-compilation (macOS → Linux) ───────────────────────

# Build for AMD64 Linux (Intel containers)
cross-amd64:
	cross build --release --target x86_64-unknown-linux-gnu

# Build for ARM64 Linux (ARM containers)
cross-arm64:
	cross build --release --target aarch64-unknown-linux-gnu

# ── Docker ───────────────────────────────────────────────────

# Build Docker image with multi-stage Rust build (AMD64)
docker-amd64:
	docker build --platform linux/amd64 -f Dockerfile -t agent-server-rust:amd64 .

# Build Docker image with multi-stage Rust build (ARM64)
docker-arm64:
	docker build --platform linux/arm64 -f Dockerfile -t agent-server-rust:arm64 .

# ── Utility ──────────────────────────────────────────────────

# Clean build artifacts
clean:
	cargo clean

# Check binary size after release build
size: release
	@ls -lh target/release/agent-server
	@echo "---"
	@size target/release/agent-server 2>/dev/null || true
