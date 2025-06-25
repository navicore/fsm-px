// audio_tracer.c - eBPF program to trace audio signatures
#include <linux/bpf.h>
#include <linux/pkt_cls.h>
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_endian.h>

// Define minimal structures we need
struct eth_hdr {
    unsigned char h_dest[6];
    unsigned char h_source[6];
    __u16 h_proto;
} __attribute__((packed));

struct iphdr {
    __u8 ihl:4;
    __u8 version:4;
    __u8 tos;
    __u16 tot_len;
    __u16 id;
    __u16 frag_off;
    __u8 ttl;
    __u8 protocol;
    __u16 check;
    __u32 saddr;
    __u32 daddr;
} __attribute__((packed));

struct tcphdr {
    __u16 source;
    __u16 dest;
    __u32 seq;
    __u32 ack_seq;
    __u16 res1:4;
    __u16 doff:4;
    __u16 fin:1;
    __u16 syn:1;
    __u16 rst:1;
    __u16 psh:1;
    __u16 ack:1;
    __u16 urg:1;
    __u16 res2:2;
    __u16 window;
    __u16 check;
    __u16 urg_ptr;
} __attribute__((packed));

#define AUDIO_PORT_SOURCE 8000
#define AUDIO_PORT_RELAY 8001
#define MAX_PACKET_SIZE 1500
#define INTERVAL_ID_LEN 36  // UUID length

// Event structure to send to userspace
struct audio_event {
    __u64 timestamp;
    __u32 src_ip;
    __u32 dst_ip;
    __u16 src_port;
    __u16 dst_port;
    char interval_id[INTERVAL_ID_LEN + 1];
    __u32 position;
    __u32 packet_len;
};

// Map to send events to userspace
struct {
    __uint(type, BPF_MAP_TYPE_PERF_EVENT_ARRAY);
    __uint(key_size, sizeof(__u32));
    __uint(value_size, sizeof(__u32));
} events SEC(".maps");

// Map to track interval_id first seen time
struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(key_size, INTERVAL_ID_LEN);
    __uint(value_size, sizeof(__u64));
    __uint(max_entries, 10000);
} interval_first_seen SEC(".maps");

// Helper to find pattern in packet data
static __always_inline int find_pattern(const char *data, int data_len, 
                                       const char *pattern, int pattern_len) {
    if (data_len < pattern_len)
        return -1;
    
    for (int i = 0; i <= data_len - pattern_len; i++) {
        int match = 1;
        for (int j = 0; j < pattern_len && j < 20; j++) {  // Limit loop
            if (data[i + j] != pattern[j]) {
                match = 0;
                break;
            }
        }
        if (match)
            return i;
    }
    return -1;
}

// Extract interval_id from SSE data
static __always_inline int extract_interval_id(struct __sk_buff *skb, 
                                               struct audio_event *event,
                                               int payload_offset) {
    char buf[200];
    int ret;
    
    // Read a chunk of the payload
    ret = bpf_skb_load_bytes(skb, payload_offset, buf, sizeof(buf));
    if (ret < 0)
        return -1;
    
    // Look for "interval_id":"
    const char pattern[] = "\"interval_id\":\"";
    int pattern_len = sizeof(pattern) - 1;
    
    int pos = find_pattern(buf, sizeof(buf), pattern, pattern_len);
    if (pos < 0)
        return -1;
    
    // Extract the UUID
    int uuid_start = pos + pattern_len;
    if (uuid_start + INTERVAL_ID_LEN > sizeof(buf))
        return -1;
    
    // Copy interval_id
    for (int i = 0; i < INTERVAL_ID_LEN && i < sizeof(event->interval_id) - 1; i++) {
        event->interval_id[i] = buf[uuid_start + i];
    }
    event->interval_id[INTERVAL_ID_LEN] = '\0';
    
    // Try to extract position too
    const char pos_pattern[] = "\"position\":";
    int pos_pos = find_pattern(buf, sizeof(buf), pos_pattern, sizeof(pos_pattern) - 1);
    if (pos_pos > 0) {
        // Simple number extraction (assumes position < 1000)
        int num_start = pos_pos + sizeof(pos_pattern) - 1;
        int num = 0;
        for (int i = 0; i < 4; i++) {
            char c = buf[num_start + i];
            if (c >= '0' && c <= '9') {
                num = num * 10 + (c - '0');
            } else {
                break;
            }
        }
        event->position = num;
    }
    
    return 0;
}

SEC("classifier/tc_audio")
int tc_audio_trace(struct __sk_buff *skb) {
    void *data = (void *)(long)skb->data;
    void *data_end = (void *)(long)skb->data_end;
    
    // Parse Ethernet header
    struct eth_hdr *eth = data;
    if ((void *)(eth + 1) > data_end)
        return TC_ACT_OK;
    
    // Only process IP packets (0x0800)
    if (eth->h_proto != bpf_htons(0x0800))
        return TC_ACT_OK;
    
    // Parse IP header
    struct iphdr *ip = (void *)(eth + 1);
    if ((void *)(ip + 1) > data_end)
        return TC_ACT_OK;
    
    // Only process TCP (protocol 6)
    if (ip->protocol != 6)
        return TC_ACT_OK;
    
    // Parse TCP header
    struct tcphdr *tcp = (void *)ip + (ip->ihl * 4);
    if ((void *)(tcp + 1) > data_end)
        return TC_ACT_OK;
    
    __u16 src_port = bpf_ntohs(tcp->source);
    __u16 dst_port = bpf_ntohs(tcp->dest);
    
    // Filter for our audio ports
    if (src_port != AUDIO_PORT_SOURCE && src_port != AUDIO_PORT_RELAY &&
        dst_port != AUDIO_PORT_SOURCE && dst_port != AUDIO_PORT_RELAY)
        return TC_ACT_OK;
    
    // Calculate payload offset
    int eth_len = sizeof(struct eth_hdr);
    int ip_len = ip->ihl * 4;
    int tcp_len = tcp->doff * 4;
    int payload_offset = eth_len + ip_len + tcp_len;
    
    // Check if we have payload
    int payload_len = skb->len - payload_offset;
    if (payload_len < 100)  // Too small for SSE event
        return TC_ACT_OK;
    
    // Create event
    struct audio_event event = {0};
    event.timestamp = bpf_ktime_get_ns();
    event.src_ip = ip->saddr;
    event.dst_ip = ip->daddr;
    event.src_port = src_port;
    event.dst_port = dst_port;
    event.packet_len = payload_len;
    
    // Try to extract interval_id from payload
    if (extract_interval_id(skb, &event, payload_offset) == 0) {
        // Check if this is first time seeing this interval_id
        __u64 *first_seen = bpf_map_lookup_elem(&interval_first_seen, event.interval_id);
        if (!first_seen) {
            __u64 now = event.timestamp;
            bpf_map_update_elem(&interval_first_seen, event.interval_id, &now, BPF_ANY);
        }
        
        // Send event to userspace
        bpf_perf_event_output(skb, &events, BPF_F_CURRENT_CPU, 
                             &event, sizeof(event));
    }
    
    return TC_ACT_OK;
}

char _license[] SEC("license") = "GPL";