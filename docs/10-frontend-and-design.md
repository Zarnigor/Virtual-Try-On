# 10. Frontend and design: what comes from the backend

Design reference: `design/` (see `design/README.md`). 12 desktop screens, Uzbek copy, tokens in `design/tokens.md`.

## Hard rule: images come from the backend
**Every image of a person or a garment shown in the UI is loaded from the backend API.** The design files draw
silhouettes and flat T-shirt/pants shapes only as placeholders. In the app:
- No bundled/hard-coded garments, avatars, bodies, outfits or sample photos in the frontend code.
- The garment catalog, "my garments", avatars, the user's body, try-on results, realistic images and saved outfits are
  all fetched from the API. Names, types, statuses and visibility come from the same records.
- Only the logo and UI icons are static assets.
- The frontend never composes the try-on picture. The backend deformation engine returns the finished 600x1200 result
  image; the UI shows it. Landmark editors draw their lines in an SVG overlay on top of the backend-served image.
- Use plain `<img src="{signed_url}">` (or CSS background where needed). No base64 in JSON, no embedding images in the bundle.
- Signed URLs are short-lived: never cache them in localStorage; on 403/expiry refetch the record to get a new URL.
- Reserve the box before the image loads (body/avatar/result: aspect 1:2; garment: stored aspect ratio) so layout does not jump;
  show a skeleton while loading and a labelled fallback on error. `alt` texts come from the record name.

## Screen map (design file -> route -> data)
| # | Screen | Route (proposal) | Calls / fields | Images from the backend |
|---|---|---|---|---|
| 1 | Kirish | /login | POST /auth/login, /auth/register | none (brand art static) |
| 2 | Bosh sahifa | / | GET /body (status), GET /garments?limit, GET /outfits?limit | body image, garment thumbs, outfit result thumbs |
| 3 | Tana tanlash | /body | GET /body (exists?), GET /avatars | avatar images for the 3 builds |
| 4 | Oʻz rasmini yuklash | /body/new | POST /body (file, 18+ flag), GET /jobs/{id} | requirement sample image (served by the backend), uploaded-photo preview while checking |
| 5 | Belgilash sahifasi | /body/landmarks | GET /body (normalized image + landmarks), POST /body/confirm | normalized body image |
| 6 | Model tanlash | /model | GET /avatars/nearest?... | nearest avatar image |
| 7 | Kiyimlar | /garments | GET /garments?scope=mine\|catalog&type= | garment thumbnails; DELETE /garments/{id} |
| 8 | Kiyim yuklash va tozalash | /garments/new | POST /garments (file, type), GET /jobs/{id}, then Save/Cancel | uploaded original (temporary preview) and cleaned result |
| 9 | Kiyimni belgilash | /garments/{id}/landmarks | PATCH landmarks, PATCH visibility | cleaned garment image |
| 10 | Kiyib koʻrish | /try-on | GET /garments, POST /tryon, POST /tryon/{id}/realistic, POST /outfits | body or avatar image, garment thumbs, result image, realistic image |
| 11 | Mening obrazlarim | /outfits | GET /outfits, DELETE /outfits/{id} | result and realistic images |
| 12 | Profil va maxfiylik | /profile | GET /body, PATCH /body/measurements, DELETE /body, DELETE /me | none |

Response fields the UI needs (add them to the API, see docs/04): `image_url` (+ `thumb_url` for lists), `width`, `height`,
`type`, `name`, `visibility`, `status`, `landmarks`, `created_at`; outfits: `result_url`, `realistic_url`, `garments[]`
with a `deleted` flag.

## States NOT drawn in the design (you must build them)
- Loading (skeletons), empty (no garments yet, no outfits, no body), and error states for every list and image.
- Async AI jobs: "tayyorlanmoqda" progress while polling `/jobs/{id}`; failed job with the mapped Uzbek reason (prompts/README.md).
- Daily AI attempt limit reached (disable upload, explain when it resets).
- Session expired / 401 -> back to login keeping the target route.
- Confirmations: body confirm (irreversible), body delete (explain that its outfits are deleted too, ask for an explicit confirm),
  garment delete, account delete.
- Measurements update locked until a year has passed (show when it unlocks).
- Moderation statuses on garments: Tekshiruvda, Yashirilgan (with reason when known), Ommaviy, Faqat men.
- Stretch/quality warning on the try-on result (amber banner as in screen 10) when the backend flags it.
- Offline / API unreachable. Demo mode (precomputed results) when enabled.

## Behaviour notes
- Screen 4: the uploaded original is only a temporary preview and is deleted after processing (docs/02 rule 6).
  Screen 8 compares original vs cleaned: keep the original only until the user presses Save or Cancel (or a short TTL),
  then delete it. (Assumption, see docs/09.)
- Screen 5/9: the editor snaps ticks to the silhouette edge, supports dragging, arrow-key nudges (1 px, Shift 10 px), zoom.
  Landmark names are fixed (docs/03). Run the sanity checks on the client AND the server.
- Screen 6: all five measurements are required. Units are cm. (Circumference vs front width: open question 13.)
- Screen 10: toggling Oddiy/Realistik switches which backend image is shown. The AI button creates a job.
- Responsive: pages stack at tablet/phone width; the landmark editor stays usable (pinch/zoom) but desktop is the target.
- All user-facing strings go through one Uzbek locale file.
