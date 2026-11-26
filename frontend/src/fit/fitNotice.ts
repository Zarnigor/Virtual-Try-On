/** Which fit notice to draw for one garment (docs/11, docs/09 #128). Pure: no React, no I/O. */
import type { FitZoneCheck } from '../api/types'
import { fitLines } from './fitMessages'

/** red = too small (not rendered when the flag is on), yellow = rendered but big, none = nothing to say. */
export type FitNoticeKind = 'red' | 'yellow' | 'none'

export interface FitNoticeView {
  kind: FitNoticeKind
  lines: string[]
}

export interface FitNoticeInput {
  fits: boolean
  checks: FitZoneCheck[]
  /** too_large zones; when absent they are taken from `checks`. */
  warnings?: FitZoneCheck[]
}

/** fits false -> red with every failing zone line (too_small and too_large, like SIZE_MISMATCH.detail);
 *  fits true with too_large zones -> yellow with the "katta" lines; otherwise none. */
export function fitNotice({ fits, checks, warnings }: FitNoticeInput): FitNoticeView {
  if (!fits) return { kind: 'red', lines: fitLines(checks) }
  const big = warnings ?? checks.filter((c) => c.verdict === 'too_large')
  const lines = fitLines(big)
  return lines.length > 0 ? { kind: 'yellow', lines } : { kind: 'none', lines: [] }
}

export interface FitWarningBlock {
  garmentId: number
  /** Garment name; only when more than one garment was tried on. */
  title: string | null
  lines: string[]
}

/** Job result `fit_warnings` -> yellow blocks. Reads an untyped job result safely; bad items are skipped.
 *  `nameOf` gives the garment name; `garmentCount` = how many garments were tried on. */
export function fitWarningBlocks(
  result: Record<string, unknown> | null | undefined,
  garmentCount: number,
  nameOf: (garmentId: number) => string,
): FitWarningBlock[] {
  const raw = result?.fit_warnings
  if (!Array.isArray(raw)) return []
  const blocks: FitWarningBlock[] = []
  for (const item of raw as unknown[]) {
    if (!item || typeof item !== 'object') continue
    const { garment_id: garmentId, checks, detail } = item as { garment_id?: unknown; checks?: unknown; detail?: unknown }
    if (typeof garmentId !== 'number') continue
    let lines = Array.isArray(checks) ? fitNotice({ fits: true, checks: [], warnings: checks as FitZoneCheck[] }).lines : []
    if (lines.length === 0 && typeof detail === 'string') lines = detail.split('\n').map((l) => l.trim()).filter(Boolean)
    if (lines.length === 0) continue
    blocks.push({ garmentId, title: garmentCount > 1 ? nameOf(garmentId) : null, lines })
  }
  return blocks
}
