# Design tokens

## Colors
| Token | Value | Use |
|---|---|---|
| bg | #0A1626 | page |
| header | #0B1B2E | top bar, left panels |
| surface | #0F2236 | cards |
| inset | #0A1A2B | inputs, image wells, stages |
| surface-hover | #112A42 / #17375A | secondary buttons |
| selected | #132E49 | active nav item, active row |
| border | #1E3A55 | card borders, dividers |
| border-strong | #2A4A68 | inputs, secondary buttons |
| text | #E8F1F8 | main text |
| text-soft | #D5E3EE / #B7CADB | body copy |
| muted | #A9BED1 | labels, helper text (min 4.5:1 on surface) |
| accent | #3DDC84 | primary button, active stepper, success; text on accent #06210F |
| accent-soft | rgba(61,220,132,.12), border rgba(61,220,132,.4), text #7CE8AE | "ok" chips, selected options |
| warning | #F5B84B (bg rgba(245,184,75,.1)) | warnings, "Tekshiruvda" |
| danger | #F29B9B (bg rgba(242,155,155,.08), border #8A4A50) | destructive actions, "Yashirilgan" |
| ai | #D9CCFF on rgba(142,111,224,.16), border #8E6FE0 | everything that is AI-paid ("Realistik") |
| silhouette | #24496C (body), #3F6AA8 (T-shirt overlay) | placeholders only |

Landmark line colors: neck #B77CFF, shoulder #FFA23D, chest #FF5C7A, waist #3DDC84, hip #5C9DFF,
knee #35D0E8, ankle #5ED0C0, guide lines #7A8CA0 (dashed). On light garment backgrounds use the darker
variants used in screen 9 (#E07A00, #D6223F, #0E8A44, #2456D8, #8E3FD0).

## Type
Headings: Space Grotesk 600/700, letter-spacing -0.01em. Body: Inter 400/500/600.
Sizes: H1 28-44, H2 18-24, body 14-16, helper 12.5-13.5 (not below 12), landmark canvas labels 12+ on screen.

## Shape and spacing
Radius: 12 (buttons, inputs), 14-16 (inner cards, wells), 20 (main cards), 999 (chips).
Buttons: min-height 44, padding 0 20, font 600 15; small: 40-44 high. Inputs: min-height 48.
Page max-width 1120-1240, side padding 32-40, card padding 24-32, gaps 16-32.

## Components (all in the screens)
Top nav with active item; segmented control (.seg: pill track, active = accent); stepper (circle states:
done = outlined with check, active = filled accent number, todo = outlined number); status chips
(neutral, green, amber, red, AI-purple); table (right-aligned numbers, tabular figures); radio option cards;
dropzone (2px dashed #3A6285); alert banners (amber); danger zone (red tint card).

## Accessibility
Real <button>/<a>/<input>+<label>; aria-label on icon-only buttons; decorative SVG aria-hidden;
text contrast >= 4.5:1; touch targets >= 44 px; do not rely on color alone for status (chips have text).
