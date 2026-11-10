# 05. AI pipeline

Prompts live in `prompts/` (see `prompts/README.md` for config, canvas rules and the error-code table).
Image model: **Nano Banana 2 (standard)** via the official Gemini API.

## Body upload pipeline
1. Code checks: file type/size, min resolution (figure height >= about 1000 px), rembg mask, exactly one person-sized component,
   head and feet in frame, arms not touching the torso, legs apart, upright and centred. Reject with a code (does not count toward the daily limit).
2. AI check: `02-body-validation.txt` (JSON). Fail closed. (P0 or P1: open question 12.)
3. Normalize to the 600x1200 canvas (figure 50..1150). Delete the original upload.
4. Auto-detect landmarks, user adjusts in LandmarkEditor, optional height/measurements, confirm -> lock.

## Garment upload pipeline (AI cleaning is in P0)
1. Code checks: file type/size, min size.
2. AI check: `01-garment-validation.txt` (JSON). Types: tshirt, pants. **The detected type must match the chosen type**
   (checked in code; a T-shirt also needs short or no sleeves), otherwise `WRONG_GARMENT_TYPE`. Every rule is re-checked in
   code (`ok: true` alone is never trusted); invalid/empty JSON -> `AI_RESPONSE_INVALID`. Verdicts are cached by image hash
   (+ declared type, prompt hash, model): a cache hit makes no AI call and uses no daily slot. Code: `apps/jobs/ai_schemas.py`,
   `apps/jobs/tasks.py` (`_check_garment_with_ai`), `apps/jobs/gemini.py`, `apps/jobs/ai_cache.py`, `apps/jobs/limits.py`.
3. AI cleaning (**optional, `AI_CLEANING_ENABLED`, default off**, docs/09 #55): `04-garment-cleaning.txt` (image model, 3:4, 1K).
   Background colour from garment brightness (white garments: #808080, otherwise #EDEDED). Not built yet: with the flag on,
   the job fails with `CLEAN_FAILED` before prompt 01 runs. **With the flag off, hanger/mannequin photos are not cleaned**:
   the hanger stays in the image wherever rembg keeps it.
4. rembg (or flat-colour keying) -> transparent PNG -> crop to the alpha bounding box. With cleaning off this is the only
   cleaning step: rembg returns the mask only, the original pixels are kept, alpha is added (`_rembg_clean`).
5. Quality check (code): compare mean colour and area/shape of the garment before/after; large difference = reject.
6. User preview: Save or Cancel. Only Save persists. Delete the original upload.
7. LandmarkEditor with the garment's landmark set; the user chooses visibility.
8. Public: `03-moderation.txt` -> approve / review / reject.

## Realistic render pipeline (P1)
1. Input: try-on composite (600x1200) + clean garment.
2. Pad to 675x1200 (9:16) with background colour, call `05-realistic-render.txt`, aspect 9:16.
3. Crop central 600 columns, resize to 600x1200.
4. Verify placement: the person's head/feet bounding boxes match the input within a few px; else retry once, then fail.
5. Save the realistic image with the outfit.

## Cost (Google list prices, June 2026; re-check before use)
- Nano Banana 2 about $0.067 per 1K image. 30 garments x 2 tries = about $4. Chosen over Lite and Pro by the owner.
- Per-user daily limit; no batch mode in the MVP.

## Demo safety
- Precompute and store results for about 10 demo garments (clean image, landmarks, try-on results) and provide a demo mode
  that uses them if the network or API is slow.
