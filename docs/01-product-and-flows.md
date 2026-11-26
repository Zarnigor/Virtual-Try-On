# 01. Product and flows

## What we are building
A 2D virtual try-on web app (MVP). Users see clothes on their own body photo or on a model avatar.
Core goal: **the clothes must fit the person's exact body size** (not just "look nice").
Context: this is a project for a job application. 3 days to build, the 4th day only for checking.
Demo-ability matters: the demo must not depend on live AI speed (keep prepared results as fallback).

## Current focus
**2026-11-26 (owner, docs/09 #130): the own body is the main try-on path** (ends the 2026-11-12 own-body pause).
The user uploads their own body photo, checks the landmarks and enters their sizes; the fit check and the render use
that body's own sizes and landmarks. Avatars (models) stay as the demo / fallback path. The try-on page opens on the
own body when it is confirmed.

## Actors
- **User**: signs in, has at most one private body, uploads garments, tries on, saves outfits.
- **Admin** (the developer): prepares 6 avatars and the starter catalog, handles the moderation queue.
- **AI services** (Google Gemini API): validation, cleaning, moderation, realistic render.

## Pages
| Page | Purpose | Priority |
|---|---|---|
| Sign in / register | Account (required: body and garments are per-user and private) | P0 |
| Create my body (main path, docs/09 #130) | Choose sex (required), upload once (A-pose), checks, mark landmarks, sizes (height, chest, waist, hip required; shoulder width estimated from the landmarks, editable; inseam optional), confirm | P0 |
| Choose model (demo / fallback) | Gender only -> that sex's average avatar (docs/09 #124) | P0 |
| Garments | Catalog (public) + My garments | P0 |
| Upload garment | Upload, cleaning (rembg; AI hanger removal is off for now, docs/09 #55), preview, mark landmarks, visibility, fit mode, gender | P0 |
| Try on | Body + garment (matching gender only, docs/09 #97), result, quality warnings (no fit label) | P0 |
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
- **My body** (the main path, docs/09 #130): one photo, once, A-pose, tight clothing, plus the user's sizes. After
  confirmation the photo and landmarks can never be changed (sizes: once per 365 days; the body may be deleted).
- **Model** (demo / fallback): 6 prepared avatars (male/female x slim/average/plus). Pick gender; that sex's average
  avatar is used (docs/09 #124); the fit check uses the avatar's own sizes (docs/09 #129).

### Garment source
- **Catalog**: admin-prepared + approved public garments. MVP garment types: T-shirt (`tshirt`) and pants (`pants`).
- **My garments**: user uploads. Choice per garment: private (only me) or public (everyone).
  Whatever the choice, the garment shows up in "My garments" immediately; moderation only gates
  visibility to OTHER users.

### Outfit ("obraz")
Saved combination: body reference + garment references + result image (+ realistic image if made).
Store references, not copies, plus the result image so deleting a garment does not break the outfit.
Saving is possible with or without the realistic render; if a realistic image exists it is saved too.
