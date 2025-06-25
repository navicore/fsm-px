use std::collections::HashMap;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;

#[derive(Debug, Clone)]
pub struct AudioEvent {
    pub timestamp_ns: u64,
    pub src_ip: String,
    pub src_port: u16,
    pub dst_ip: String, 
    pub dst_port: u16,
    pub interval_id: String,
    pub position: u32,
}

#[derive(Debug)]
pub struct LatencyMeasurement {
    pub interval_id: String,
    pub source_timestamp_ns: u64,
    pub relay_timestamp_ns: u64,
    pub latency: Duration,
}

pub struct EbpfProcessor {
    // Track first seen time for each interval_id at source
    interval_first_seen: HashMap<String, u64>,
    // Track latencies for each interval_id
    latency_measurements: Vec<LatencyMeasurement>,
}

impl EbpfProcessor {
    pub fn new() -> Self {
        Self {
            interval_first_seen: HashMap::new(),
            latency_measurements: Vec::new(),
        }
    }
    
    pub fn process_trace_file(&mut self, path: &Path) -> Result<(), Box<dyn std::error::Error>> {
        let file = File::open(path)?;
        let reader = BufReader::new(file);
        
        for line in reader.lines() {
            let line = line?;
            if let Some(event) = self.parse_trace_line(&line) {
                self.process_event(event);
            }
        }
        
        Ok(())
    }
    
    fn parse_trace_line(&self, line: &str) -> Option<AudioEvent> {
        // Parse CSV format from eBPF output
        // Format: timestamp,src_ip,src_port,dst_ip,dst_port,interval_id,position,packet_len
        let parts: Vec<&str> = line.split(',').collect();
        
        if parts.len() < 7 {
            return None;
        }
        
        // Skip header line
        if parts[0] == "timestamp" {
            return None;
        }
        
        Some(AudioEvent {
            timestamp_ns: parts[0].parse().ok()?,
            src_ip: parts[1].to_string(),
            src_port: parts[2].parse().ok()?,
            dst_ip: parts[3].to_string(),
            dst_port: parts[4].parse().ok()?,
            interval_id: parts[5].to_string(),
            position: parts[6].parse().ok()?,
        })
    }
    
    fn process_event(&mut self, event: AudioEvent) {
        // Is this from the source (port 8000)?
        if event.src_port == 8000 {
            // First time seeing this interval_id from source
            if !self.interval_first_seen.contains_key(&event.interval_id) {
                self.interval_first_seen.insert(event.interval_id.clone(), event.timestamp_ns);
                println!("Source: interval_id {} first seen at position {}", 
                         event.interval_id, event.position);
            }
        }
        
        // Is this arriving at relay (port 8001)?
        if event.dst_port == 8001 {
            if let Some(&source_time) = self.interval_first_seen.get(&event.interval_id) {
                let latency_ns = event.timestamp_ns - source_time;
                let latency = Duration::from_nanos(latency_ns);
                
                let measurement = LatencyMeasurement {
                    interval_id: event.interval_id.clone(),
                    source_timestamp_ns: source_time,
                    relay_timestamp_ns: event.timestamp_ns,
                    latency,
                };
                
                println!("Latency: interval_id {} position {} = {:?}", 
                         event.interval_id, event.position, latency);
                
                self.latency_measurements.push(measurement);
            }
        }
    }
    
    pub fn get_statistics(&self) -> (Duration, Duration, Duration) {
        if self.latency_measurements.is_empty() {
            return (Duration::ZERO, Duration::ZERO, Duration::ZERO);
        }
        
        let latencies: Vec<Duration> = self.latency_measurements
            .iter()
            .map(|m| m.latency)
            .collect();
        
        let sum: Duration = latencies.iter().sum();
        let avg = sum / latencies.len() as u32;
        let min = *latencies.iter().min().unwrap();
        let max = *latencies.iter().max().unwrap();
        
        (min, avg, max)
    }
    
    pub fn export_prometheus_metrics(&self) {
        // Export to Prometheus format
        println!("# HELP audio_latency_seconds Audio processing latency in seconds");
        println!("# TYPE audio_latency_seconds histogram");
        
        for measurement in &self.latency_measurements {
            let latency_secs = measurement.latency.as_secs_f64();
            println!("audio_latency_seconds{{interval_id=\"{}\",source=\"ebpf\"}} {}", 
                     measurement.interval_id, latency_secs);
        }
    }
}