// audio_tracer_user.c - Userspace component for audio tracer
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <signal.h>
#include <time.h>
#include <arpa/inet.h>
#include <linux/if_link.h>
#include <net/if.h>

#include <bpf/bpf.h>
#include <bpf/libbpf.h>

// Must match the kernel structure
struct audio_event {
    __u64 timestamp;
    __u32 src_ip;
    __u32 dst_ip;
    __u16 src_port;
    __u16 dst_port;
    char interval_id[37];
    __u32 position;
    __u32 packet_len;
};

static volatile bool running = true;
static FILE *output_file = NULL;

// Signal handler
static void sig_handler(int sig) {
    running = false;
}

// Convert IP to string
static void ip_to_str(__u32 ip, char *buf) {
    struct in_addr addr = { .s_addr = ip };
    strcpy(buf, inet_ntoa(addr));
}

// Handle perf event
static void handle_event(void *ctx, int cpu, void *data, __u32 data_sz) {
    struct audio_event *e = data;
    char src_ip[16], dst_ip[16];
    
    if (data_sz < sizeof(*e))
        return;
    
    ip_to_str(e->src_ip, src_ip);
    ip_to_str(e->dst_ip, dst_ip);
    
    // Write CSV format to file
    fprintf(output_file, "%llu,%s,%u,%s,%u,%s,%u,%u\n",
            e->timestamp, src_ip, e->src_port, dst_ip, e->dst_port,
            e->interval_id, e->position, e->packet_len);
    fflush(output_file);
    
    // Also print to console
    printf("[%llu] %s:%u -> %s:%u | interval_id=%s pos=%u len=%u\n",
           e->timestamp, src_ip, e->src_port, dst_ip, e->dst_port,
           e->interval_id, e->position, e->packet_len);
}

int main(int argc, char **argv) {
    struct bpf_object *obj = NULL;
    struct bpf_program *prog = NULL;
    struct perf_buffer *pb = NULL;
    int prog_fd, map_fd;
    int err;
    
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <interface> <output_file>\n", argv[0]);
        return 1;
    }
    
    const char *iface = argv[1];
    const char *output_path = argv[2];
    
    // Open output file
    output_file = fopen(output_path, "w");
    if (!output_file) {
        fprintf(stderr, "Failed to open output file: %s\n", strerror(errno));
        return 1;
    }
    
    // Write CSV header
    fprintf(output_file, "timestamp,src_ip,src_port,dst_ip,dst_port,interval_id,position,packet_len\n");
    
    // Set up signal handler
    signal(SIGINT, sig_handler);
    signal(SIGTERM, sig_handler);
    
    // Load BPF program
    obj = bpf_object__open_file("audio_tracer.o", NULL);
    if (libbpf_get_error(obj)) {
        fprintf(stderr, "Failed to open BPF object\n");
        return 1;
    }
    
    // Load into kernel
    err = bpf_object__load(obj);
    if (err) {
        fprintf(stderr, "Failed to load BPF object: %s\n", strerror(-err));
        goto cleanup;
    }
    
    // Find our program
    prog = bpf_object__find_program_by_name(obj, "tc_audio_trace");
    if (!prog) {
        fprintf(stderr, "Failed to find tc_audio_trace program\n");
        goto cleanup;
    }
    
    prog_fd = bpf_program__fd(prog);
    
    // Attach to TC
    DECLARE_LIBBPF_OPTS(bpf_tc_hook, tc_hook, .ifindex = if_nametoindex(iface));
    DECLARE_LIBBPF_OPTS(bpf_tc_opts, tc_opts, .handle = 1, .priority = 1);
    
    // Create clsact qdisc
    tc_hook.attach_point = BPF_TC_INGRESS;
    err = bpf_tc_hook_create(&tc_hook);
    if (err && err != -EEXIST) {
        fprintf(stderr, "Failed to create TC hook: %s\n", strerror(-err));
        goto cleanup;
    }
    
    // Attach program
    tc_opts.prog_fd = prog_fd;
    err = bpf_tc_attach(&tc_hook, &tc_opts);
    if (err) {
        fprintf(stderr, "Failed to attach TC program: %s\n", strerror(-err));
        goto cleanup;
    }
    
    printf("Attached to interface %s\n", iface);
    
    // Set up perf buffer
    map_fd = bpf_object__find_map_fd_by_name(obj, "events");
    if (map_fd < 0) {
        fprintf(stderr, "Failed to find events map\n");
        goto cleanup;
    }
    
    pb = perf_buffer__new(map_fd, 64, handle_event, NULL, NULL, NULL);
    if (libbpf_get_error(pb)) {
        fprintf(stderr, "Failed to create perf buffer\n");
        goto cleanup;
    }
    
    printf("Tracing audio packets... Press Ctrl+C to stop.\n");
    
    // Main event loop
    while (running) {
        err = perf_buffer__poll(pb, 100);
        if (err < 0 && err != -EINTR) {
            fprintf(stderr, "Error polling perf buffer: %s\n", strerror(-err));
            break;
        }
    }
    
cleanup:
    // Detach program
    if (prog_fd > 0) {
        tc_opts.flags = tc_opts.prog_fd = tc_opts.prog_id = 0;
        bpf_tc_detach(&tc_hook, &tc_opts);
    }
    
    if (pb)
        perf_buffer__free(pb);
    if (obj)
        bpf_object__close(obj);
    if (output_file)
        fclose(output_file);
    
    return 0;
}