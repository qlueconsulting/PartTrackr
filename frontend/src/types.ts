export interface ApiLogEntry {
  id: string
  timestamp: string
  level: 'info' | 'success' | 'warn' | 'error'
  service: string
  message: string
  details?: any
}

export interface BoundingBox {
  x: number
  y: number
  w: number
  h: number
}

export interface NoteElement {
  pitch?: string | null
  midi_pitch?: number | null
  duration_quarters: number
  duration_type: string
  offset_quarters: number
  stem_direction?: 'up' | 'down' | null
  is_rest: boolean
  is_chord?: boolean
  chord_pitches?: string[]
  lyric?: string | null
  bounding_box?: BoundingBox | null
}

export interface TrackData {
  track_name: string
  clef: string
  elements: NoteElement[]
}

export interface StaffInfo {
  staff_id: string
  index: number
  clef: string
  bracket_type: 'bracket' | 'brace' | 'none'
  role: string
  y_top: number
  y_bot: number
  has_lyrics: boolean
  label?: string | null
}

export interface MeasureData {
  measure_number: number
  time_signature: string
  tempo_bpm: number
  quarter_length: number
  bounding_box?: BoundingBox | null
  raw_staves?: Record<string, TrackData>
  tracks?: Record<string, TrackData>
}

export interface SystemData {
  system_index: number
  page_num: number
  bounding_box: BoundingBox
  crop_image_path?: string
  staves: StaffInfo[]
  measures: MeasureData[]
}

export interface ScoreCISM {
  score_id: string
  title: string
  composer: string
  subtitle?: string | null
  page_count: number
  total_systems: number
  total_measures: number
  has_piano: boolean
  systems: SystemData[]
  metadata?: Record<string, any>
}

export interface LayoutPageData {
  page_num: number
  image_path: string
  width_pt: number
  height_pt: number
  width_px: number
  height_px: number
  systems: any[]
}

export interface LayoutResult {
  job_id: string
  title: string
  composer: string
  page_count: number
  dpi: number
  total_systems: number
  total_measures: number
  has_piano: boolean
  pages: LayoutPageData[]
  systems: any[]
}

export interface DecoderResult {
  job_id: string
  status: string
  score_musicxml_path: string
  score_midi_path: string
  sync_map_path: string
  stems: Record<string, { musicxml_path: string; midi_path: string }>
  measure_summary: MeasureInfo[]
  total_measures: number
  total_duration_seconds: number
}

export type PipelineStage = 'pending' | 'layout' | 'omr' | 'routing' | 'decoding' | 'completed' | 'failed'

export interface PreflightData {
  job_id?: string
  title: string
  composer: string
  subtitle?: string | null
  page_count: number
  time_signature: string
  tempo_bpm: number
  choral_voicing: string
  accompaniment_type: string
  has_piano: boolean
  staves_per_system: number
  part_layout_summary: string
  voice_labels_detected?: string[]
}

export interface JobData {
  job_id: string
  status: PipelineStage
  stage_message: string
  title: string
  composer: string
  page_count: number
  total_measures: number
  total_duration_seconds: number
  created_at?: string
  layout_data?: LayoutResult | null
  raw_cism?: ScoreCISM | null
  routed_cism?: ScoreCISM | null
  decoder_result?: DecoderResult | null
  overrides?: Record<string, any> | null
  score_hints?: ScoreHints | null
  error_message?: string | null
}

export interface ChannelState {
  volume: number // 0.0 to 1.5
  pan: number // -1.0 to 1.0
  muted: boolean
  soloed: boolean
  amplified?: boolean // +6dB boost
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
  entrances?: string[]
}

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
  notes?: string[]
  warnings: string[]
}

export interface ScoreHints {
  total_measures?: number | null
  choral_voicing?: string | null
  accompaniment_type?: string | null
  time_signature?: string | null
  tempo_bpm?: number | null
  custom_instructions?: string | null
}

export interface ScoreResponse {
  id: string
  title: string
  composer: string
  original_filename: string
  file_type: string
  status: string
  status_message?: string
  created_at: string
  measure_count: number
  total_duration_seconds: number
  time_signature: string
  tempo_bpm: number
  stems: Record<string, StemInfo>
  analysis: MeasureInfo[]
  audit?: AuditReport
  score_hints?: ScoreHints
}

export const CANONICAL_11_PARTS = [
  'soprano_1',
  'soprano_2',
  'alto_1',
  'alto_2',
  'tenor_1',
  'tenor_2',
  'baritone_1',
  'baritone_2',
  'bass_1',
  'bass_2',
  'piano',
] as const

export type CanonicalPart = typeof CANONICAL_11_PARTS[number]

export const PART_DISPLAY_NAMES: Record<CanonicalPart, string> = {
  soprano_1: 'Soprano I',
  soprano_2: 'Soprano II',
  alto_1: 'Alto I',
  alto_2: 'Alto II',
  tenor_1: 'Tenor I',
  tenor_2: 'Tenor II',
  baritone_1: 'Baritone I',
  baritone_2: 'Baritone II',
  bass_1: 'Bass I',
  bass_2: 'Bass II',
  piano: 'Piano Accompaniment',
}
