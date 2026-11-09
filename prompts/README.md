# Prompts

Raw prompt texts, loaded by the backend (`{PLACEHOLDER}` values are filled in code).
Do not paraphrase or "improve" them without testing (see testing notes below).

| File | Model type | Input | Output | API config |
|---|---|---|---|---|
| 01-garment-validation.txt | vision (text out) | garment photo + `GARMENT_TYPE` | JSON | temperature 0, JSON response schema |
| 02-body-validation.txt | vision (text out) | body photo | JSON | temperature 0, JSON response schema |
| 03-moderation.txt | vision (text out) | cleaned garment (+ optional report reason) | JSON | temperature 0, JSON response schema |
| 04-garment-cleaning.txt | image model | garment photo + `GARMENT_TYPE`, `BACKGROUND_HEX` | image (or text `NO_GARMENT`) | `aspectRatio: "3:4"`, `imageSize: "1K"` |
| 05-realistic-render.txt | image model | Image 1 (try-on composite), Image 2 (clean garment) | image (or text `NO_EDIT`) | `aspectRatio: "9:16"`, `imageSize: "1K"` |

MVP garment types: `tshirt` (short sleeve or sleeveless) and `pants`. Anything else is rejected as WRONG_TYPE.

Image model: **Nano Banana 2 (standard)**, chosen by the owner (not Lite, not Pro). Verify the current model ID in the Gemini docs.

## Rules for every call
- Validation prompts return strict JSON. Validate it with Pydantic. If the reply is empty,
  invalid or missing fields: treat the image as REJECTED (fail closed). Never let it through.
- The model returns codes. The backend maps codes to Uzbek user messages (table below).
- Use the official Google Gemini API only. Check current model names and prices in the docs
  before wiring (preview names change).
- Cost control: code checks run BEFORE any AI call. Count only AI-reaching attempts toward the
  daily upload limit.
- AI text outputs `NO_GARMENT` / `NO_EDIT` mean "no image returned": treat as rejection.

## Canvas rules (important)
- Project canvas for body, avatars and try-on results: **600 x 1200** (width x height).
- Gemini image aspect ratios do NOT include 1:2. Supported: 1:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4,
  9:16, 16:9, 21:9 (verify in current docs).
- Garment cleaning (04): request 3:4, then in code: rembg -> transparent PNG -> crop to alpha
  bounding box. Store the garment as a tight-cropped transparent PNG (do NOT force 600x1200).
- Realistic render (05): the composite is 600x1200. Pad left/right with the background color to
  675x1200 (9:16), send with `aspectRatio: "9:16"`, then crop the central 600 columns back and
  resize to 600x1200 if needed. Verify the person's head/feet bounding box matches Image 1
  within a few pixels; otherwise retry or reject.

## Error code -> Uzbek user message
| Code | Message |
|---|---|
| NOT_FULL_BODY | Toʻliq boʻy tushing: bosh va oyoqlar kadrda boʻlsin. |
| NOT_FRONT_FACING | Kameraga old tomoningiz bilan turing. |
| NOT_UPRIGHT | Tik turing. |
| ARMS_NOT_AWAY | Qoʻllaringizni tanadan biroz uzoqroq oching. |
| LEGS_NOT_APART | Oyoqlaringizni yelka kengligida oching. |
| LONG_SLEEVES | Kalta yengli yoki yengsiz kiyimda tushing (yeng tirsakdan yuqorida tugasin). |
| LOOSE_OR_THICK_CLOTHING / LONG_GARMENT | Qalin yoki keng kiyim aniqlandi. Tor sport kiyimida qayta tushing. |
| OBJECT_OR_ACCESSORY | Bosh kiyim, sumka yoki qoʻlingizdagi narsani olib tashlang. |
| MULTIPLE_PEOPLE | Rasmda faqat siz boʻlishingiz kerak. |
| NO_PERSON | Rasmda odam topilmadi. |
| POOR_LIGHTING / BLURRY | Yorugʻroq joyda, aniq rasm tushing. |
| NOT_A_REAL_PHOTO | Haqiqiy fotosurat yuklang. |
| APPARENT_MINOR / ESTIMATE_UNCLEAR | Bu rasmni qabul qila olmaymiz. Boshqa rasm yuklab koʻring. (Sababni batafsil yozmang.) |
| NO_GARMENT / NOT_A_CLOTHING_PHOTO | Rasmda kiyim topilmadi. |
| MULTIPLE_GARMENTS | Rasmda bitta kiyim boʻlsin. |
| WRONG_TYPE | Tanlangan tur rasmdagi kiyimga mos emas. Hozircha faqat futbolka va shim qabul qilinadi. |
| NOT_FRONT_VIEW | Kiyimning old tomonini yuklang. |
| GARMENT_CUT_OFF | Kiyim toʻliq koʻrinsin, chetlari kesilmasin. |
| LOW_QUALITY | Rasm xira yoki kichik. Aniqroq rasm yuklang. |

Code-side (non-AI) checks have their own codes: ARMS_TOUCH_BODY, LEGS_TOUCH, IMAGE_TOO_SMALL,
HEAD_OR_FEET_CUT, FILE_TOO_LARGE, BAD_FILE_TYPE. Map them to similar Uzbek messages.

## Moderation outcome
- `approve` -> add to public catalog
- `review` -> admin queue (not public until approved)
- `reject` -> hidden. If categories contain CHILD_SAFETY: hide immediately and alert the admin.

## Testing before production
Test every prompt on 6-10 real images: one good, one bad per rejection code, and borderline cases
(not tight but not baggy clothing). If a case fails, add ONE concrete rule at the end of that
prompt for that case and retest. For prompts 04 and 05 check: logo/lettering unchanged, color
preserved, no hanger remains, no body change.
