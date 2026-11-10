/**
 * API contract: the single source of truth for request/response shapes on the frontend.
 * Mirrors docs/04-data-model-and-api.md ("API contract"). If you change one, change the other
 * and the Django serializers/views in the same commit.
 *
 * All URLs are relative to the API base (VITE_API_URL) and end with a slash (Django style).
 * All image fields are short-lived signed URLs: never cache them, refetch the record on 403/404.
 */

// ---------- common ----------

/** Error body for non-2xx responses we produce ourselves. DRF field errors are Record<field, string[]>. */
export interface ApiError {
  code?: string
  detail?: string
  [field: string]: unknown
}

export type JobKind = 'body_validation' | 'garment_clean' | 'tryon' | 'moderation' | 'realistic'
export type JobStatus = 'queued' | 'running' | 'done' | 'failed'

export interface Job {
  id: number
  kind: JobKind
  status: JobStatus
  result: Record<string, unknown> | null
  error_code: string
  /** Uzbek message mapped by the backend from error_code; null when there is no error. */
  error_message: string | null
  created_at: string
  updated_at: string
}

// ---------- auth ----------

export interface User {
  id: number
  email: string
  is_adult_confirmed: boolean
  created_at: string
}

export interface RegisterRequest {
  email: string
  password: string
  is_adult_confirmed: boolean
}

export interface LoginRequest {
  email: string
  password: string
}

/** Returned by POST auth/register/ (201) and POST auth/login/ (200). */
export interface AuthResponse {
  user: User
  access: string
  refresh: string
}

// ---------- landmarks (docs/03) ----------

export interface Span {
  y: number
  left_x: number
  right_x: number
  width?: number
  center_x?: number
}

export interface LegSpan {
  left_x: number
  right_x: number
  width?: number
  y?: number
}

export interface Point {
  x: number
  y: number
}

/** Body landmarks on the 600x1200 canvas. Names are fixed (docs/03). */
export interface BodyLandmarks {
  head_top: { y: number }
  neck: Span
  shoulder: Span
  armpit: { y: number }
  chest: Span
  waist: Span
  hip: Span
  crotch: { y: number; center_x?: number }
  knee: { y: number; left_leg: LegSpan; right_leg: LegSpan }
  ankle: { left_leg: LegSpan & { y: number }; right_leg: LegSpan & { y: number } }
  foot_bottom: { y: number }
}

/** T-shirt landmarks, pixels on the garment's own tight-cropped PNG. */
export interface TshirtLandmarks {
  shoulder: Span
  chest: Span
  waist: Span
  hem: Span
  sleeve_end: { left: Point; right: Point }
}

/** Pants landmarks, pixels on the garment's own tight-cropped PNG. */
export interface PantsLandmarks {
  waist: Span
  hip: Span
  crotch: { y: number; center_x?: number }
  knee: { y: number; left_leg: LegSpan; right_leg: LegSpan }
  hem: { left_leg: LegSpan & { y: number }; right_leg: LegSpan & { y: number } }
}

/** Empty object until the landmarks are marked. */
export type GarmentLandmarks = TshirtLandmarks | PantsLandmarks | Record<string, never>

// ---------- body ----------

/** Circumferences in cm (decision 13). All optional for the own body. */
export interface Measurements {
  shoulder?: number
  chest?: number
  waist?: number
  hip?: number
}

export interface Body {
  id: number
  /** Normalized 600x1200 image. */
  image_url: string | null
  /** Empty object until confirmed (or until auto-detection fills it). */
  landmarks: Partial<BodyLandmarks>
  height_cm: number | null
  measurements: Measurements | null
  /** null until confirmed; after that photo + landmarks are immutable. */
  confirmed_at: string | null
  /** When the yearly measurements lock ends; null if never changed. */
  measurements_unlock_at: string | null
  can_change_measurements: boolean
  created_at: string
}

/** POST body/ is multipart: photo (File) + is_adult_confirmed ("true"). */
export interface BodyUploadResponse {
  body: Body
  job_id: number
}

/** POST body/confirm/ */
export interface BodyConfirmRequest {
  landmarks: BodyLandmarks
  height_cm?: number | null
  measurements?: Measurements | null
}

/** PATCH body/measurements/ (once per 365 days). */
export interface MeasurementsUpdateRequest {
  height_cm?: number | null
  measurements?: Measurements | null
}

// ---------- avatars ----------

export type Sex = 'male' | 'female'
export type Build = 'slim' | 'average' | 'plus'

export interface Avatar {
  id: number
  sex: Sex
  build: Build
  image_url: string | null
  landmarks: Partial<BodyLandmarks>
  /** Reference circumferences in cm. */
  measurements: Measurements
}

/** GET avatars/nearest/ query. Model path: all measurements required (rule 20). */
export interface NearestAvatarQuery {
  sex: Sex
  height: number
  shoulder: number
  chest: number
  waist: number
  hip: number
}

// ---------- garments ----------

export type GarmentType = 'tshirt' | 'pants'
export type Visibility = 'private' | 'public'
export type GarmentStatus = 'pending' | 'approved' | 'review' | 'hidden'
export type GarmentScope = 'mine' | 'catalog' | 'all'

export interface Garment {
  id: number
  name: string
  type: GarmentType
  /** Cleaned transparent PNG. */
  image_url: string | null
  thumb_url: string | null
  /** Temporary: only until the user presses Save/Cancel after cleaning. */
  original_preview_url: string | null
  width: number | null
  height: number | null
  landmarks: GarmentLandmarks
  visibility: Visibility
  status: GarmentStatus
  owned_by_me: boolean
  /** True = the AI check was skipped (AI_DEV_BYPASS, local dev only): NOT validated. Show a dev warning. */
  ai_skipped: boolean
  created_at: string
}

/** POST garments/ is multipart: photo (File) + type + name?. */
export interface GarmentUploadResponse {
  garment: Garment
  job_id: number
}

// ---------- try-on and outfits ----------

export interface TryOnRequest {
  base: 'body' | 'avatar'
  avatar_id?: number
  /** At most one garment per type (max 2). */
  garment_ids: number[]
}

/** GET /api/config/ (public). */
export interface AppConfig {
  /** Backend runs with DEMO_MODE=1: some try-on results are precomputed (job.result.demo = true). */
  demo_mode: boolean
}

export interface TryOnResponse {
  job_id: number
  outfit_id: number
}

export interface Outfit {
  id: number
  body: number | null
  avatar: number | null
  garments: Garment[]
  result_url: string | null
  realistic_url: string | null
  created_at: string
}
