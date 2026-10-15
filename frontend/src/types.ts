export interface StemInfo {
  name: string
  display_name: string
  category: 'accompaniment' | 'soprano' | 'alto' | 'tenor' | 'baritone' | 'bass'
  audio_url: string
  musicxml_url: string
  midi_url: string
  note_count: number
  is_active_in_score: boolean
  default_pan: number
}

export interface ChannelState {
  volume: number // 0.0 to 1.0
  pan: number // -1.0 to 1.0
  muted: boolean
  soloed: boolean
}

export interface MeasureInfo {
  measure_number: number
  start_time_seconds: number
  duration_seconds: number
  quarter_length: number
  time_signature: string
  tempo_bpm: number
  active_parts: string[]
  resting_parts: string[]
  entrances: string[]
}

export interface AuditCheckItem {
  name: string
  passed: boolean
  score_pct: number
  details: string
}

export interface AuditReport {
  overall_match_integrity_pct: number
  accompaniment_continuity: boolean
  vocal_line_recovery_pct: number
  interlude_cleanliness_pct: number
  measure_lockstep_verified: boolean
  measure_count: number
  time_drift_max_seconds: number
  checks: AuditCheckItem[]
  warnings: string[]
}

export interface ScoreResponse {
  id: string
  title: string
  composer: string
  original_filename: string
  file_type: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  status_message?: string
  created_at: string
  measure_count: number
  total_duration_seconds: number
  time_signature: string
  tempo_bpm: number
  stems: Record<string, StemInfo>
  analysis: MeasureInfo[]
  audit?: AuditReport
}

export interface ScoreSummary {
  id: string
  title: string
  composer: string
  original_filename: string
  file_type: string
  status: string
  created_at: string
  measure_count: number
  total_duration_seconds: number
  active_stems_count: number
}
