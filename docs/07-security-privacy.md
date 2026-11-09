# 07. Security and privacy

- Body photo is personal data (a body image). Minimize: originals are deleted after normalization/cleaning (decided);
  store only what is needed; per-user access only; signed URLs; no logging of image content.
- Show a short consent text before body upload (what is stored, who sees it: only the owner).
- Account deletion should delete body, photos, outfits and private garments.
- Prompt injection: AI prompts state that text inside images is content, not instructions. Treat any AI output
  as untrusted; validate JSON strictly.
- Uploads: validate file type by content, limit size and dimensions, strip EXIF (GPS), re-encode images.
- Rate limits: daily upload attempts per user, auth throttling, global AI budget cap.
- Moderation: public garments pass AI moderation; report button; hide on several reports; CHILD_SAFETY
  categories hide immediately and alert the admin.
- No features that remove clothing or sexualize images.
- Use only official Google APIs; no third-party resellers (data and reliability risk).
- Secrets via environment variables only; never in the repo.
