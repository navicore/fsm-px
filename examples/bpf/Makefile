CC = gcc
CLANG = clang
CFLAGS = -O2 -g -Wall
BPF_CFLAGS = -O2 -g -Wall -target bpf -D__TARGET_ARCH_x86
LDFLAGS = -lbpf -lelf -lz

# Architecture detection
ARCH := $(shell uname -m | sed 's/x86_64/x86/' | sed 's/aarch64/arm64/')
ifeq ($(ARCH),arm64)
    BPF_CFLAGS = -O2 -g -Wall -target bpf -D__TARGET_ARCH_arm64
endif

# Default target
all: audio_tracer.o audio_tracer_user

# Build eBPF program
audio_tracer.o: audio_tracer.c
	$(CLANG) $(BPF_CFLAGS) -c $< -o $@

# Build userspace program
audio_tracer_user: audio_tracer_user.c
	$(CC) $(CFLAGS) $< -o $@ $(LDFLAGS)

# Clean
clean:
	rm -f audio_tracer.o audio_tracer_user

.PHONY: all clean