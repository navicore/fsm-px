use crate::config::{MeasurementConfig, VadMode};
use std::collections::VecDeque;

/// Stateful detector that processes audio packets and finds signature points
pub struct SignatureDetector {
    config: MeasurementConfig,
    audio_buffer: VecDeque<Vec<u8>>,
    packet_counter: u32,
}

impl SignatureDetector {
    pub fn new(config: MeasurementConfig) -> Self {
        Self {
            config,
            audio_buffer: VecDeque::with_capacity(100),
            packet_counter: 0,
        }
    }

    /// Process a packet and potentially generate a signature
    pub fn process_packet(&mut self, payload: &[u8]) -> Option<SignatureEvent> {
        self.packet_counter += 1;

        // Sample according to configured rate
        if self.packet_counter % self.config.signature_rules.sampling_rate != 0 {
            return None;
        }

        // Extract metadata first (it's always there, even if we don't use this packet)
        let metadata = self.extract_metadata(payload);

        // Buffer audio for duration analysis
        self.audio_buffer.push_back(payload.to_vec());
        if self.audio_buffer.len() > 50 {
            self.audio_buffer.pop_front();
        }

        // Check if this is a signature-worthy moment
        if self.is_signature_worthy() {
            let signature = self.generate_signature();

            return Some(SignatureEvent {
                signature,
                metadata,
                timestamp: std::time::Instant::now(),
                measurement_name: self.config.name.clone(),
            });
        }

        None
    }

    fn extract_metadata(&self, payload: &[u8]) -> PacketMetadata {
        let mut metadata = PacketMetadata::default();

        // Skip to where metadata lives
        let envelope_start = self.config.metadata_extraction.header_offset;
        if payload.len() <= envelope_start {
            return metadata;
        }

        // Try each ID pattern
        for pattern in &self.config.metadata_extraction.id_patterns {
            if pattern.pattern.starts_with("\\x") {
                // Binary pattern matching
                if let Some(pos) = self.find_bytes(payload, &pattern.pattern) {
                    let id_start = pos + pattern.value_offset as usize;
                    let id_end = id_start + pattern.value_length;
                    if id_end <= payload.len() {
                        let id_bytes = &payload[id_start..id_end];
                        let id = String::from_utf8_lossy(id_bytes).to_string();
                        metadata.ids.insert(pattern.id_type.clone(), id);
                    }
                }
            } else {
                // Regex pattern (for JSON, etc)
                let text = String::from_utf8_lossy(&payload[envelope_start..]);
                if let Ok(re) = regex::Regex::new(&pattern.pattern) {
                    if let Some(cap) = re.captures(&text) {
                        if let Some(id) = cap.get(1) {
                            metadata
                                .ids
                                .insert(pattern.id_type.clone(), id.as_str().to_string());
                        }
                    }
                }
            }
        }

        metadata
    }

    fn is_signature_worthy(&self) -> bool {
        // Implement VAD logic based on configured mode
        match &self.config.signature_rules.audio_criteria.vad_mode {
            VadMode::Energy => self.check_energy_threshold(),
            VadMode::ZeroCrossing => self.check_zero_crossing_rate(),
            VadMode::Spectral => self.check_spectral_features(),
            VadMode::ML { model_path } => self.run_ml_vad(model_path),
        }
    }

    fn check_energy_threshold(&self) -> bool {
        // Simple RMS energy calculation
        let total_samples: usize = self
            .audio_buffer
            .iter()
            .map(|chunk| chunk.len() / 2) // Assuming 16-bit audio
            .sum();

        if total_samples == 0 {
            return false;
        }

        let mut energy = 0.0;
        for chunk in &self.audio_buffer {
            for i in (0..chunk.len()).step_by(2) {
                if i + 1 < chunk.len() {
                    let sample = i16::from_le_bytes([chunk[i], chunk[i + 1]]);
                    energy += (sample as f32).powi(2);
                }
            }
        }

        let rms = (energy / total_samples as f32).sqrt() / 32768.0; // Normalize
        rms > self.config.signature_rules.audio_criteria.energy_threshold
    }

    fn check_zero_crossing_rate(&self) -> bool {
        // Count sign changes (good indicator of speech vs silence)
        let mut crossings = 0;
        let mut prev_sign = 0i8;

        for chunk in &self.audio_buffer {
            for i in (0..chunk.len()).step_by(2) {
                if i + 1 < chunk.len() {
                    let sample = i16::from_le_bytes([chunk[i], chunk[i + 1]]);
                    let sign = sample.signum() as i8;
                    if prev_sign != 0 && sign != prev_sign {
                        crossings += 1;
                    }
                    prev_sign = sign;
                }
            }
        }

        // Speech typically has 10-30 crossings per 10ms
        // This is a simplified check
        crossings > 50
    }

    fn check_spectral_features(&self) -> bool {
        // TODO: Implement FFT-based detection
        // Would check for formant frequencies typical of speech
        false
    }

    fn run_ml_vad(&self, model_path: &str) -> bool {
        // TODO: Load ONNX/TF Lite model for VAD
        false
    }

    fn generate_signature(&self) -> AudioSignature {
        // Create a compact signature from the buffered audio
        // Using perceptual hash or spectral fingerprint

        // For now, simple hash of energy profile
        let mut hasher = xxhash_rust::xxh3::Xxh3::new();

        // Hash energy values over time windows
        for chunk in &self.audio_buffer {
            let energy = self.chunk_energy(chunk);
            hasher.update(&energy.to_le_bytes());
        }

        AudioSignature {
            hash: hasher.digest(),
            duration_ms: (self.audio_buffer.len() * 20) as u32, // Assuming 20ms chunks
        }
    }

    fn chunk_energy(&self, chunk: &[u8]) -> f32 {
        let mut sum = 0.0;
        for i in (0..chunk.len()).step_by(2) {
            if i + 1 < chunk.len() {
                let sample = i16::from_le_bytes([chunk[i], chunk[i + 1]]);
                sum += (sample as f32).abs();
            }
        }
        sum / (chunk.len() as f32 / 2.0)
    }

    fn find_bytes(&self, haystack: &[u8], pattern: &str) -> Option<usize> {
        // Convert \x00\x42 style pattern to bytes
        // This is simplified - real impl would parse hex properly
        None // TODO
    }
}

#[derive(Debug, Clone)]
pub struct SignatureEvent {
    pub signature: AudioSignature,
    pub metadata: PacketMetadata,
    pub timestamp: std::time::Instant,
    pub measurement_name: String,
}

#[derive(Debug, Clone)]
pub struct AudioSignature {
    pub hash: u64,
    pub duration_ms: u32,
}

#[derive(Debug, Clone, Default)]
pub struct PacketMetadata {
    pub ids: std::collections::HashMap<String, String>,
}
