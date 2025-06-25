// tc_loader.go - Userspace loader for TC eBPF audio tracer
package main

import (
	"bytes"
	"encoding/binary"
	"encoding/csv"
	"fmt"
	"log"
	"net"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/cilium/ebpf"
	"github.com/cilium/ebpf/ringbuf"
	"github.com/cilium/ebpf/rlimit"
	"github.com/vishvananda/netlink"
	"golang.org/x/sys/unix"
)

// Must match the C structure
type AudioEvent struct {
	TimestampNs  uint64
	SrcIP        uint32
	DstIP        uint32
	SrcPort      uint16
	DstPort      uint16
	IntervalID   [37]byte
	Position     uint32
	FoundInterval uint8
	_            [3]byte // padding
}

func main() {
	if err := run(); err != nil {
		log.Fatalf("Error: %v", err)
	}
}

func run() error {
	// Remove memory limit for eBPF
	if err := rlimit.RemoveMemlock(); err != nil {
		return fmt.Errorf("failed to remove memlock: %w", err)
	}

	// Load eBPF program
	spec, err := ebpf.LoadCollectionSpec("tc_audio_tracer.o")
	if err != nil {
		return fmt.Errorf("failed to load eBPF spec: %w", err)
	}

	coll, err := ebpf.NewCollection(spec)
	if err != nil {
		return fmt.Errorf("failed to create collection: %w", err)
	}
	defer coll.Close()

	// Get the TC program
	prog := coll.Programs["tc_audio_trace"]
	if prog == nil {
		return fmt.Errorf("program tc_audio_trace not found")
	}

	// Find all veth interfaces and attach TC
	interfaces, err := findVethInterfaces()
	if err != nil {
		return fmt.Errorf("failed to find interfaces: %w", err)
	}

	log.Printf("Found %d veth interfaces", len(interfaces))

	// Attach to each interface
	var filters []*netlink.BpfFilter
	for _, iface := range interfaces {
		// Attach to ingress
		f, err := attachTC(prog, iface, true)
		if err != nil {
			log.Printf("Failed to attach to %s ingress: %v", iface, err)
			continue
		}
		filters = append(filters, f)
		
		// Also attach to egress
		f, err = attachTC(prog, iface, false)
		if err != nil {
			log.Printf("Failed to attach to %s egress: %v", iface, err)
			continue
		}
		filters = append(filters, f)
		
		log.Printf("Attached to interface %s", iface)
	}

	if len(filters) == 0 {
		return fmt.Errorf("failed to attach to any interface")
	}

	defer func() {
		for _, f := range filters {
			netlink.FilterDel(f)
		}
	}()

	// Open output CSV file
	outputFile, err := os.Create("/output/tc_trace.csv")
	if err != nil {
		return fmt.Errorf("failed to create output file: %w", err)
	}
	defer outputFile.Close()

	csvWriter := csv.NewWriter(outputFile)
	defer csvWriter.Flush()

	// Write header
	csvWriter.Write([]string{
		"timestamp_ns", "src_ip", "src_port", "dst_ip", "dst_port", 
		"interval_id", "position", "direction",
	})

	// Open ringbuf reader
	rd, err := ringbuf.NewReader(coll.Maps["events"])
	if err != nil {
		return fmt.Errorf("failed to create ringbuf reader: %w", err)
	}
	defer rd.Close()

	// Handle signals
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt, syscall.SIGTERM)

	log.Println("Listening for events... Press Ctrl+C to stop")

	// Stats
	var totalEvents, eventsWithInterval uint64
	ticker := time.NewTicker(10 * time.Second)
	defer ticker.Stop()

	// Read events
	go func() {
		for {
			record, err := rd.Read()
			if err != nil {
				if err == ringbuf.ErrClosed {
					return
				}
				log.Printf("Error reading ringbuf: %v", err)
				continue
			}

			// Parse event
			var event AudioEvent
			if err := binary.Read(bytes.NewReader(record.RawSample), binary.LittleEndian, &event); err != nil {
				log.Printf("Error parsing event: %v", err)
				continue
			}

			totalEvents++
			
			// Convert IPs
			srcIP := intToIP(event.SrcIP)
			dstIP := intToIP(event.DstIP)
			
			// Extract interval ID (null-terminated string)
			intervalID := string(bytes.TrimRight(event.IntervalID[:], "\x00"))
			
			// Determine direction
			direction := "unknown"
			if event.SrcPort == 8000 {
				direction = "from_source"
			} else if event.DstPort == 8001 {
				direction = "to_relay"
			}
			
			// Only log events with interval_id
			if event.FoundInterval > 0 && intervalID != "" {
				eventsWithInterval++
				csvWriter.Write([]string{
					fmt.Sprintf("%d", event.TimestampNs),
					srcIP, fmt.Sprintf("%d", event.SrcPort),
					dstIP, fmt.Sprintf("%d", event.DstPort),
					intervalID, fmt.Sprintf("%d", event.Position),
					direction,
				})
				csvWriter.Flush()
				
				log.Printf("Captured: %s:%d -> %s:%d interval_id=%s dir=%s",
					srcIP, event.SrcPort, dstIP, event.DstPort, 
					intervalID, direction)
			}
		}
	}()

	// Wait for signal or stats
	for {
		select {
		case <-sig:
			log.Println("Received signal, exiting...")
			return nil
		case <-ticker.C:
			log.Printf("Stats: %d total events, %d with interval_id (%.1f%%)",
				totalEvents, eventsWithInterval,
				float64(eventsWithInterval)/float64(totalEvents+1)*100)
		}
	}
}

func findVethInterfaces() ([]string, error) {
	links, err := netlink.LinkList()
	if err != nil {
		return nil, err
	}

	var interfaces []string
	for _, link := range links {
		// Check if it's a veth interface
		if link.Type() == "veth" {
			interfaces = append(interfaces, link.Attrs().Name)
		}
	}
	
	return interfaces, nil
}

func attachTC(prog *ebpf.Program, ifaceName string, ingress bool) (*netlink.BpfFilter, error) {
	iface, err := net.InterfaceByName(ifaceName)
	if err != nil {
		return nil, fmt.Errorf("failed to get interface %s: %w", ifaceName, err)
	}

	// Ensure clsact qdisc exists
	qdisc := &netlink.GenericQdisc{
		QdiscAttrs: netlink.QdiscAttrs{
			LinkIndex: iface.Index,
			Handle:    netlink.MakeHandle(0xffff, 0),
			Parent:    netlink.HANDLE_CLSACT,
		},
		QdiscType: "clsact",
	}
	
	// Try to add, ignore "exists" error
	if err := netlink.QdiscAdd(qdisc); err != nil && !strings.Contains(err.Error(), "exists") {
		return nil, fmt.Errorf("failed to add clsact qdisc: %w", err)
	}

	// Attach filter
	var parent uint32
	if ingress {
		parent = netlink.HANDLE_MIN_INGRESS
	} else {
		parent = netlink.HANDLE_MIN_EGRESS
	}

	filter := &netlink.BpfFilter{
		FilterAttrs: netlink.FilterAttrs{
			LinkIndex: iface.Index,
			Parent:    parent,
			Priority:  1,
			Protocol:  unix.ETH_P_ALL,
		},
		Fd:           prog.FD(),
		Name:         "tc_audio_trace",
		DirectAction: true,
	}

	if err := netlink.FilterAdd(filter); err != nil {
		return nil, fmt.Errorf("failed to add filter: %w", err)
	}

	// Return the filter for cleanup
	return filter, nil
}

func intToIP(ip uint32) string {
	return fmt.Sprintf("%d.%d.%d.%d", ip&0xff, (ip>>8)&0xff, (ip>>16)&0xff, (ip>>24)&0xff)
}