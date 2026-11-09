# 01. Product and flows

## What we are building
A 2D virtual try-on web app (MVP). Users see clothes on their own body photo or on a model avatar.
Core goal: **the clothes must fit the person's exact body size** (not just "look nice").
Context: this is a project for a job application. 3 days to build, the 4th day only for checking.
Demo-ability matters: the demo must not depend on live AI speed (keep prepared results as fallback).

## Actors
- **User**: signs in, has at most one private body, uploads garments, tries on, saves outfits.
- **Admin** (the developer): prepares 6 avatars and the starter catalog, handles the moderation queue.
- **AI services** (Google Gemini API): validation, cleaning, moderation, realistic render.

## Pages
| Page | Purpose | Priority |
|---|---|---|
| Sign in / register | Account (required: body and garments are per-user and private) | P0 |
| Create my body | Upload once (A-pose), checks, mark landmarks, optional height, confirm | P0 |
| Choose model | Gender + optional measurements -> nearest avatar | P0 |
| Garments | Catalog (public) + My garments | P0 |
| Upload garment | Upload, AI cleaning (hanger removal), preview, mark landmarks, visibility | P0 |
| Try on | Body + garment, result, fit indicator | P0 |
| Realistic render button | AI redraw of a try-on result | P1 |
| My outfits | Saved outfits | P1 |
| Public garments: moderation, report button | Visible to others | P2 |
| Landmark editor | ONE reusable component used in 3 places (see below) | P0 |
| Admin | Seed 6 avatars by a seed command, no separate page needed | P0 (no UI) |

## The Landmark editor (do not forget)
One React component (`LandmarkEditor`), used in three places with different landmark sets:
1. Admin avatars (body landmark set)
2. User's own body (body landmark set)
3. Uploaded garment (garment landmark set by garment type)
Prototype: `tools/landmark-editor-prototype/body-landmarks.html` (vanilla JS, port to React).
Details: `03-landmarks-and-coordinates.md`.

## Flows (see diagrams in `docs/diagrams/`)
- Activity 1: create own body
- Activity 2: upload garment, clean, mark, public/private, moderation
- Activity 3: try on, realistic render, save outfit

### Body source
User chooses either:
- **My body**: one photo, once, A-pose, tight clothing. After confirmation it can never be changed.
  (Deleting the account/body for privacy is a separate decision, see open questions.)
- **Model**: 6 prepared avatars (male/female x slim/average/plus). Pick gender; the nearest build is
  chosen from optional measurements; the garment is deformed to the entered measurements.

### Garment source
- **Catalog**: admin-prepared + approved public garments. MVP garment types: T-shirt (`tshirt`) and pants (`pants`).
- **My garments**: user uploads. Choice per garment: private (only me) or public (everyone).
  Whatever the choice, the garment shows up in "My garments" immediately; moderation only gates
  visibility to OTHER users.

### Outfit ("obraz")
Saved combination: body reference + garment references + result image (+ realistic image if made).
Store references, not copies, plus the result image so deleting a garment does not break the outfit.
Saving is possible with or without the realistic render; if a realistic image exists it is saved too.
