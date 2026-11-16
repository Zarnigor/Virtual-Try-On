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
  /** Staff see the /staff pages (avatar editor). */
  is_staff: boolean
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
  /** head_top, armpit, crotch, foot_bottom: left_x / right_x are set by the staff editor and auto-detection. */
  head_top: { y: number; left_x?: number; right_x?: number }
  neck: Span
  shoulder: Span
  armpit: { y: number; left_x?: number; right_x?: number }
  chest: Span
  waist: Span
  hip: Span
  crotch: { y: number; center_x?: number; left_x?: number; right_x?: number }
  knee: { y: number; left_leg: LegSpan; right_leg: LegSpan }
  ankle: { left_leg: LegSpan & { y: number }; right_leg: LegSpan & { y: number } }
  foot_bottom: { y: number; left_x?: number; right_x?: number }
}

/**
 * T-shirt landmarks, pixels on the garment's own tight-cropped PNG (docs/03, docs/09 #92). left/right = image
 * left/right. armpit, collar, collar_bottom are optional for now. The cuff corners replace `sleeve_end`, which
 * old records still carry (read only: the server never writes it).
 */
export interface TshirtLandmarks {
  shoulder: Span
  chest: Span
  waist: Span
  hem: Span
  sleeve_cuff_outer: { left: Point; right: Point }
  sleeve_cuff_inner: { left: Point; right: Point }
  armpit?: Span
  /** Collar edges at the shoulder line. */
  collar?: Span
  /** Lowest centre point of the neckline. */
  collar_bottom?: Point
  /** Legacy (before 2026-11-11), read only. */
  sleeve_end?: { left: Point; right: Point }
  /**
   * Neckline hole (docs/09 #102, step 2 of the editor): the inner edge of the collar band, [x, y] in px of the
   * cleaned PNG, 3..64 points. Used by the MLS try-on only (TRYON_WARP=mls; adapt and keep_shape). null = no hole.
   */
  neck_hole?: { polygon: [number, number][] } | null
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
  /** Chosen at upload. null only on bodies created before it was required: ask once (PATCH body/sex/). */
  sex: Sex | null
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

// ---------- staff (is_staff only; others get 404) ----------

/** GET staff/avatars/, GET staff/avatars/{id}/ */
export interface StaffAvatar extends Avatar {
  height_cm: number | null
  landmarks_confirmed_at: string | null
  /** confirmed = saved in the editor; auto = auto-detected starting point. */
  status: 'confirmed' | 'auto'
}

/** PATCH staff/avatars/{id}/landmarks/ */
export interface StaffLandmarksRequest {
  landmarks: BodyLandmarks
  height_cm?: number | null
  measurements?: Measurements
}

/** GET avatars/nearest/ query. Model path: all measurements required (rule 20). */
export interface NearestAvatarQuery {
  sex: Sex
  /** Not used by the matching yet. */
  height?: number
  shoulder: number
  chest: number
  waist: number
  hip: number
}

// ---------- garments ----------

export type GarmentType = 'tshirt' | 'pants'
export type Visibility = 'private' | 'public'
/** docs/09 #93: adapt = deformed to the body landmarks; keep_shape = keeps its own proportions (MLS preset A when TRYON_WARP=mls, docs/09 #96, #98). */
export type FitMode = 'adapt' | 'keep_shape'
export type GarmentGender = 'female' | 'male' | 'unisex'
/** PATCH garments/{id}/: only these fields are editable (never the image). */
export interface GarmentSettings { fit_mode?: FitMode; gender?: GarmentGender }
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
  /** True when every point of the MAIN set (step 1) exists; false: ask the user to add the missing points. */
  landmarks_complete: boolean
  /** T-shirt step 2 done: collar points + collar_bottom + neck_hole polygon. null for pants (docs/09 #102). */
  neck_complete: boolean | null
  visibility: Visibility
  fit_mode: FitMode
  gender: GarmentGender
  status: GarmentStatus
  owned_by_me: boolean
  /** True = the AI check was skipped (AI_DEV_BYPASS, local dev only): NOT validated. Show a dev warning. */
  ai_skipped: boolean
  created_at: string
}

/** A range warning from PATCH garments/{id}/landmarks/ (saved anyway). */
export interface LandmarkWarning { code: 'collar_far' | 'outside_garment'; group: string; detail: string }

/** PATCH garments/{id}/landmarks/ response. */
export type GarmentLandmarksResponse = Garment & { landmark_warnings: LandmarkWarning[] }

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
  /** Debug (docs/09 #98): the T-shirt engine asked for; the job result has the one used + quality_warnings. */
  engine: 'parts' | 'mls'
}

/** What a T-shirt render actually used (docs/09 #105). engine "parts": only fit_mode and engine are present. */
export interface TshirtConfig {
  fit_mode: 'adapt' | 'keep_shape'
  engine: 'parts' | 'mls'
  /** keep_shape on MLS only (docs/09 #112): present ("fit") when the fit scale was used. */
  keep_scale?: 'fit'
  /** MLS sleeve variant; null for keep_shape. */
  sleeve?: 'r7' | 'A' | 'B' | 'C' | null
  /** Tube sleeves; false after a tube_fallback. */
  tube?: boolean
  side_floor?: 'mask' | 'off'
  /** "off" also when the tube or the side floor is off. */
  armpit?: 'r14' | 'off'
  /** "mls" = no hem post-processing. */
  hem?: 'garment' | 'mls'
  /** Tube sleeves (docs/09 #106): the garment's real sleeve hem on the cuff line; "chord" also when the tube is off. */
  cuff?: 'hem' | 'chord'
  /** Tube sleeves (docs/09 #106): photo-fringe px over solid fabric not drawn; "keep" also when the tube is off. */
  fringe?: 'drop' | 'keep'
}

/** job.result of a finished try-on job (docs/04). */
export interface TryOnJobResult {
  outfit_id: number
  /** The T-shirt engine actually used. */
  engine: 'parts' | 'mls'
  /** e.g. "mls_fallback", "neck_hole_invalid", "tube_fallback" (messages: locale TRYON_QUALITY). */
  quality_warnings: string[]
  /** Debug (docs/09 #102): per garment id, whether the owner's neckline polygon was used. */
  neck_hole: Record<string, boolean>
  /** Debug (docs/09 #105): per T-shirt garment id, the config used. Absent in demo results. */
  tshirt_config?: Record<string, TshirtConfig>
  /** Debug (docs/09 #107, #108): "r17" = a garment got the finish (smooth edge, form shading, contact shadow). Absent in demo results. */
  finish?: 'r17' | 'off'
  /** Debug (docs/09 #105): time of the render call in ms. Absent in demo results. */
  render_ms?: number
  demo?: boolean
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

/** POST tryon/ 400: garment gender does not match the base (docs/09 #97). */
export interface GenderMismatchError {
  code: 'GENDER_MISMATCH'
  detail: string
  garment_id: number
  garment_gender: GarmentGender
  base_sex: Sex
}

/** GET garments/?for_sex=: male / female also return unisex; all = no filter. */
export type ForSex = Sex | 'all'
