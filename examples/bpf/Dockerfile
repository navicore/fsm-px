FROM ubuntu:22.04 AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    clang \
    llvm \
    gcc \
    make \
    libbpf-dev \
    libelf-dev \
    linux-headers-generic \
    linux-libc-dev \
    pkg-config \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set up proper include paths for BPF compilation
ENV C_INCLUDE_PATH=/usr/include/x86_64-linux-gnu

WORKDIR /build

# Copy source files
COPY audio_tracer.c audio_tracer_user.c Makefile ./

# Build
RUN make

# Runtime image
FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    libbpf-dev \
    libelf1 \
    iproute2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy built binaries
COPY --from=builder /build/audio_tracer.o /build/audio_tracer_user ./

# Create output directory
RUN mkdir -p /output

# Entry point script
RUN cat > /app/run.sh << 'EOF'
#!/bin/bash
set -e

echo "Starting audio tracer on interface $INTERFACE"
echo "Output will be written to /output/trace.csv"

# Find the interface if not specified
if [ -z "$INTERFACE" ]; then
    # Try to find an interface with our pod IPs
    INTERFACE=$(ip link | grep -E "veth|cali" | head -1 | cut -d: -f2 | tr -d ' @')
    echo "Auto-detected interface: $INTERFACE"
fi

# Run the tracer
exec ./audio_tracer_user "$INTERFACE" /output/trace.csv
EOF

RUN chmod +x /app/run.sh

ENTRYPOINT ["/app/run.sh"]