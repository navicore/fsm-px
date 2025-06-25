// tc_audio_tracer.c - TC eBPF program for container traffic
#include <linux/bpf.h>
#include <linux/pkt_cls.h>
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_endian.h>

// Define network structures ourselves to avoid header issues
struct ethhdr {
    unsigned char h_dest[6];
    unsigned char h_source[6];
    __u16 h_proto;
} __attribute__((packed));

struct iphdr {
    __u8 ihl:4,
         version:4;
    __u8 tos;
    __be16 tot_len;
    __be16 id;
    __be16 frag_off;
    __u8 ttl;
    __u8 protocol;
    __sum16 check;
    __be32 saddr;
    __be32 daddr;
} __attribute__((packed));

struct tcphdr {
    __be16 source;
    __be16 dest;
    __be32 seq;
    __be32 ack_seq;
    __u16 res1:4,
          doff:4,
          fin:1,
          syn:1,
          rst:1,
          psh:1,
          ack:1,
          urg:1,
          ece:1,
          cwr:1;
    __be16 window;
    __sum16 check;
    __be16 urg_ptr;
} __attribute__((packed));

// Constants
#define AUDIO_PORT_SOURCE 8000
#define AUDIO_PORT_RELAY 8001
#define INTERVAL_ID_LEN 36
#define ETH_P_IP 0x0800
#define IPPROTO_TCP 6

// Event structure for userspace
struct audio_event {
    __u64 timestamp_ns;
    __u32 src_ip;
    __u32 dst_ip;
    __u16 src_port;
    __u16 dst_port;
    char interval_id[INTERVAL_ID_LEN + 1];
    __u32 position;
    __u8 found_interval;
};

// Map for sending events to userspace via ringbuf (more reliable than perf)
struct {
    __uint(type, BPF_MAP_TYPE_RINGBUF);
    __uint(max_entries, 256 * 1024); // 256KB buffer
} events SEC(".maps");

// Helper to check if memory access is safe
static __always_inline int check_bounds(void *start, void *end, void *ptr, __u32 size) {
    if ((void *)(ptr + size) > end)
        return -1;
    return 0;
}

// Simple pattern search for "interval_id":"
static __always_inline int find_interval_id(void *data, void *data_end, 
                                           struct audio_event *event) {
    char pattern[] = "\"interval_id\":\"";
    int pattern_len = sizeof(pattern) - 1;
    char *payload = data;
    
    // Ensure we have enough data
    if (check_bounds(data, data_end, payload, pattern_len + INTERVAL_ID_LEN + 2) < 0)
        return -1;
    
    // Search for pattern - unroll loop for verifier
    #pragma unroll
    for (int i = 0; i < 200; i++) {  // Search first 200 bytes
        if (payload + i + pattern_len + INTERVAL_ID_LEN > (char *)data_end)
            break;
            
        // Check pattern match byte by byte
        int match = 1;
        #pragma unroll
        for (int j = 0; j < 15; j++) {  // pattern length
            if (j >= pattern_len)
                break;
            if (payload[i + j] != pattern[j]) {
                match = 0;
                break;
            }
        }
        
        if (match) {
            // Found pattern, extract interval_id
            #pragma unroll
            for (int k = 0; k < INTERVAL_ID_LEN; k++) {
                if (payload + i + pattern_len + k >= (char *)data_end)
                    break;
                event->interval_id[k] = payload[i + pattern_len + k];
            }
            event->interval_id[INTERVAL_ID_LEN] = '\0';
            event->found_interval = 1;
            return 0;
        }
    }
    
    return -1;
}

SEC("tc")
int tc_audio_trace(struct __sk_buff *skb) {
    void *data_end = (void *)(long)skb->data_end;
    void *data = (void *)(long)skb->data;
    
    // Parse Ethernet header
    struct ethhdr *eth = data;
    if (check_bounds(data, data_end, eth, sizeof(*eth)) < 0)
        return TC_ACT_OK;
    
    // Only process IP packets
    if (bpf_ntohs(eth->h_proto) != ETH_P_IP)
        return TC_ACT_OK;
    
    // Parse IP header
    struct iphdr *ip = data + sizeof(*eth);
    if (check_bounds(data, data_end, ip, sizeof(*ip)) < 0)
        return TC_ACT_OK;
    
    // Only process TCP
    if (ip->protocol != IPPROTO_TCP)
        return TC_ACT_OK;
    
    // Parse TCP header
    __u32 ip_hlen = ip->ihl * 4;
    if (ip_hlen < sizeof(*ip))
        return TC_ACT_OK;
        
    struct tcphdr *tcp = data + sizeof(*eth) + ip_hlen;
    if (check_bounds(data, data_end, tcp, sizeof(*tcp)) < 0)
        return TC_ACT_OK;
    
    // Extract ports
    __u16 src_port = bpf_ntohs(tcp->source);
    __u16 dst_port = bpf_ntohs(tcp->dest);
    
    // Filter for audio service ports
    if (src_port != AUDIO_PORT_SOURCE && src_port != AUDIO_PORT_RELAY &&
        dst_port != AUDIO_PORT_SOURCE && dst_port != AUDIO_PORT_RELAY)
        return TC_ACT_OK;
    
    // Calculate TCP payload offset
    __u32 tcp_hlen = tcp->doff * 4;
    if (tcp_hlen < sizeof(*tcp))
        return TC_ACT_OK;
        
    void *payload = data + sizeof(*eth) + ip_hlen + tcp_hlen;
    
    // Check if we have substantial payload (SSE events are >400 bytes)
    if (payload + 400 > data_end)
        return TC_ACT_OK;
    
    // Reserve space in ringbuf for event
    struct audio_event *event = bpf_ringbuf_reserve(&events, sizeof(*event), 0);
    if (!event)
        return TC_ACT_OK;
    
    // Initialize event
    __builtin_memset(event, 0, sizeof(*event));
    event->timestamp_ns = bpf_ktime_get_ns();
    event->src_ip = ip->saddr;
    event->dst_ip = ip->daddr;
    event->src_port = src_port;
    event->dst_port = dst_port;
    event->found_interval = 0;
    
    // Try to find interval_id in payload
    find_interval_id(payload, data_end, event);
    
    // Submit event
    bpf_ringbuf_submit(event, 0);
    
    return TC_ACT_OK;
}

char _license[] SEC("license") = "GPL";