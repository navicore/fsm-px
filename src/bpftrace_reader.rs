use notify::{watcher, RecursiveMode, Watcher};
use std::collections::HashMap;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::sync::mpsc::channel;
use std::time::Duration;

#[derive(Debug, Clone)]
pub struct AudioChunkTrace {
    pub timestamp_ns: u64,
    pub src_port: u16,
    pub dst_port: u16,
    pub interval_id: String,
    pub position: u32,
}

pub struct BpftraceReader {
    trace_file: String,
    interval_first_seen: HashMap<String, u64>,
    interval_latencies: HashMap<String, Vec<Duration>>,
}

impl BpftraceReader {
    pub fn new(trace_file: &str) -> Self {
        Self {
            trace_file: trace_file.to_string(),
            interval_first_seen: HashMap::new(),
            interval_latencies: HashMap::new(),
        }
    }

    pub fn start_monitoring(&mut self) -> Result<(), Box<dyn std::error::Error>> {
        // Watch the trace file for changes
        let (tx, rx) = channel();
        let mut watcher = watcher(tx, Duration::from_millis(100))?;
        watcher.watch(&self.trace_file, RecursiveMode::NonRecursive)?;

        // Read existing content
        self.read_trace_file()?;

        // Monitor for new lines
        loop {
            match rx.recv() {
                Ok(_) => {
                    self.read_trace_file()?;
                }
                Err(e) => eprintln!("Watch error: {:?}", e),
            }
        }
    }

    fn read_trace_file(&mut self) -> Result<(), Box<dyn std::error::Error>> {
        let file = File::open(&self.trace_file)?;
        let reader = BufReader::new(file);

        for line in reader.lines() {
            let line = line?;
            if let Some(trace) = self.parse_trace_line(&line) {
                self.process_trace(trace);
            }
        }

        Ok(())
    }

    fn parse_trace_line(&self, line: &str) -> Option<AudioChunkTrace> {
        // Parse CSV format: timestamp,src_port,dst_port,interval_id,position
        let parts: Vec<&str> = line.split(',').collect();
        if parts.len() < 5 {
            return None;
        }

        Some(AudioChunkTrace {
            timestamp_ns: parts[0].parse().ok()?,
            src_port: parts[1].parse().ok()?,
            dst_port: parts[2].parse().ok()?,
            interval_id: parts[3].to_string(),
            position: parts[4].parse().ok()?,
        })
    }

    fn process_trace(&mut self, trace: AudioChunkTrace) {
        // First time seeing this interval_id at source (port 8000)?
        if trace.src_port == 8000 && !self.interval_first_seen.contains_key(&trace.interval_id) {
            self.interval_first_seen
                .insert(trace.interval_id.clone(), trace.timestamp_ns);
            println!(
                "New audio interval started: {} at position {}",
                trace.interval_id, trace.position
            );
        }

        // Seeing it at relay (port 8001)?
        if trace.dst_port == 8001 {
            if let Some(first_seen) = self.interval_first_seen.get(&trace.interval_id) {
                let latency_ns = trace.timestamp_ns - first_seen;
                let latency = Duration::from_nanos(latency_ns);

                self.interval_latencies
                    .entry(trace.interval_id.clone())
                    .or_insert_with(Vec::new)
                    .push(latency);

                println!(
                    "Latency for {} position {}: {:?}",
                    trace.interval_id, trace.position, latency
                );
            }
        }
    }

    pub fn get_latency_stats(&self) -> HashMap<String, Duration> {
        let mut avg_latencies = HashMap::new();

        for (interval_id, latencies) in &self.interval_latencies {
            if !latencies.is_empty() {
                let sum: Duration = latencies.iter().sum();
                let avg = sum / latencies.len() as u32;
                avg_latencies.insert(interval_id.clone(), avg);
            }
        }

        avg_latencies
    }
}
