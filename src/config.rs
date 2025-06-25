use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct MeasurementConfig {
    pub name: String,
    pub enabled: bool,
    pub signature_rules: SignatureRules,
    pub metadata_extraction: MetadataExtraction,
    pub correlation: CorrelationConfig,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct SignatureRules {
    /// PxL filter to identify candidate streams
    pub stream_filter: String,

    /// Audio detection criteria
    pub audio_criteria: AudioCriteria,

    /// How often to sample (every N packets)
    pub sampling_rate: u32,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct AudioCriteria {
    /// Minimum audio duration in ms to consider
    pub min_duration_ms: u32,

    /// Energy threshold (0.0 - 1.0) to detect speech
    pub energy_threshold: f32,

    /// Voice activity detection mode
    pub vad_mode: VadMode,

    /// Optional frequency range for speech detection
    pub frequency_range: Option<(f32, f32)>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub enum VadMode {
    /// Simple energy-based detection
    Energy,
    /// Zero-crossing rate for speech/silence
    ZeroCrossing,
    /// Spectral features (more CPU intensive)
    Spectral,
    /// ML-based VAD (requires model)
    ML { model_path: String },
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct MetadataExtraction {
    /// Packet offset where metadata typically appears
    pub header_offset: usize,

    /// Pattern to find UUID/segment ID
    pub id_patterns: Vec<IdPattern>,

    /// Protocol-specific parsing
    pub protocol: ProtocolType,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct IdPattern {
    /// Regex or byte pattern
    pub pattern: String,

    /// What type of ID this represents
    pub id_type: String, // "interval_id", "segment_id", "call_id"

    /// Byte offset from pattern match
    pub value_offset: i32,

    /// Length of the ID value
    pub value_length: usize,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub enum ProtocolType {
    /// Raw RTP packets
    RTP,
    /// Custom protocol with JSON envelope
    JsonEnvelope { schema: String },
    /// Binary protocol with fixed offsets
    Binary { field_map: Vec<FieldMapping> },
    /// Let user provide custom parser
    Custom { parser_script: String },
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct FieldMapping {
    pub name: String,
    pub offset: usize,
    pub length: usize,
    pub encoding: String, // "utf8", "u32_be", etc
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct CorrelationConfig {
    /// How long to keep signatures in memory
    pub signature_ttl_seconds: u64,

    /// Maximum concurrent measurements
    pub max_active_signatures: usize,

    /// How to group related measurements
    pub grouping_key: String, // e.g., "interval_id"
}
