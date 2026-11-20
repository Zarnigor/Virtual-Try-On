# Handoff (2026-11-20)

Yangi sessiyani shu fayldan boshlang. Bitta handoff fayl: eski `NEXT_STEPS.md` va `docs/11-session-handoff.md`
oʻchirilgan (tarixi git da, raundlar tarixi `docs/06`, qarorlar `docs/09`, oxirgisi #120).
Ish qoidalari: `CLAUDE.md` "How to work with me" (avval reja, egasining roziligini kutish, bitta qadam, raqamlar,
yangi teshik 0, toza rasmlar).

## 1. Holat

- Branch `tshirt-mls-default`, round 26 commit qilingan (shu fayl bilan birga). Git remote yoʻq.
- `prompts/04-garment-cleaning.txt` (1-qatorda ortiqcha "is") va `smt.txt` atayin commit qilinmagan.
- 415 backend test oʻtgan (2026-11-20). Engine oʻzgarganidan keyin `docker compose restart worker`.

## 2. Oxirgi ishlar

- **#119 drape margin** (`TRYON_DRAPE_BODY_MARGIN`, default 6 px): futbolkaning shim ustidan drape i figura
  cheti + 6 px da toʻxtaydi; qorin "shishishi" 35–85 px -> 13–21 px.
- **#120 round 26: rows shim modeli qayta yozildi** (docs/06 "Pants fit, round 26"). Bel -> crotch = figura + 3 %,
  oʻqda uchrashuvchi ikki yarim; oyoqlar tana crotch idan pastda oʻz eniga ochiladi (20 % smoothstep, cap 1.8x),
  chetlar monoton; etak ankle chizigʻida; `pants_edge` (eroziyasiz, 3 px halqa oddiy matodan). #59 / #60 hang /
  #61 / #62 / #70 / #118 (`TRYON_PANTS_FIT_X`, `TRYON_PANTS_HANG`) va round 25 oʻchirilgan; yangi sozlama yoʻq.
  Blok tanadan chiqishi 30–52k -> 7.6k px (bir shim, 6 avatar). Runner `tools/warp-benchmark/run_pants26.py`,
  diagnoz `tools/tryon_check/pants_diag.py`, sheet lar `tools/warp-benchmark/out/pants26/`.

## 3. Keyingi qadam (egasi tanlaydi)

- **#48 etak tirqishi** endi oyoqni koʻrsatadi (240–348 px): ochiq qoldirish yoki yopish. **Egasi: keyin hal
  qilinadi (2026-11-20).**
- #47 + #51 avatar 4: futbolka etagi "quloq" burchagi ostida 18 px fon choʻntagi (yangi teshik).
- Uzun shim endi poyabzal ustini yopmaydi; jogger cuff lari torayishmaydi (monoton oyoq); avatar 5 da oyoq chetida
  1–3 px pogʻona qolishi mumkin.

## 4. Hali ochiq ishlar (eski NEXT_STEPS.md dan, egasi tartibni hal qiladi)

- **Yenglar:** keep_shape yenglari yon tomonga turib qoladi (#44, tube faqat adapt da); #40 dagi siqilgan cuff;
  qoʻltiqdagi qora nuqta (#43 / #47 / #40); #47 yelka tepasida teri; #45 notekis cuff.
- **Oversize (keep_shape):** yelka choki qoʻl chizigʻi boʻylab yotishi kerak (5–66 px yuqorida turadi); tor
  garment keep_shape boʻlsa juda katta chiqadi (#47).
- **Adapt futbolka choʻzilishi va etak qoidasi:** qisqa futbolka uzunlikda x1.17–1.28 choʻziladi; etak qoidasi
  ochiq (docs/09 #91); #47 etak burchaklari "quloq" (drape ularni kattalashtiradi); #28 da 2–5 px pogʻonali torso cheti.
- **Shim:** #48 etak tirqishi (yuqorida); shorts va oq / qora shimlar oʻlchanmagan.
- **Tezlik:** adapt futbolka render ~1.1–1.5 s; demo natijalari eski (`build_demo`).
- **Mahsulot:** prompt 02 ulanmagan; prompt 04 oʻchiq, 05 yoʻq; screen 8 Save / Cancel yoʻq; avatar landmarklari
  oʻlchamlarga moslanmaydi; P2 (moderatsiya va h.k.); ESLint yoʻq; git remote / push ni egasi bilan hal qilish.

## 5. Buyruqlar

```
export PATH=$PATH:~/.orbstack/bin
docker compose up -d                                   # db, redis, backend :8000, worker, frontend :5173
docker compose exec -T backend python manage.py test apps --noinput      # 415 test, ~10 min
docker compose exec -T frontend npx tsc --noEmit
docker compose exec -T frontend npm test -- --run
docker compose exec -T backend python manage.py shell < tools/tryon_check/own_body_path.py   # ALL OK
docker compose restart worker                          # engine oʻzgarganidan keyin
# round 26 (before ni eski kodda saqlash kerak, endi faqat after):
docker compose exec -T -e MODE=after backend python manage.py shell < tools/warp-benchmark/run_pants26.py
docker compose cp backend:/tmp/warp_benchmark/pants26/. tools/warp-benchmark/out/pants26/
# qorin / drape tekshiruvi:
docker compose exec -T backend python manage.py shell < tools/tryon_check/belly_overlay.py
docker compose cp backend:/tmp/belly_overlay/. tools/tryon_check/out/belly/
```
Engine oʻzgarishlari bir xil tartibda: eski xatti-harakatni default qiladigan keyword, before | after sheet lar va
gate (yangi teshik 0) bilan runner, keyin sozlama (`settings/base.py` + `flags.py`, `docker-compose.yml` x2,
`.env.example`, README, job natijasi oʻzgarsa `frontend/src/api/types.ts`), docs/06 + docs/09, CLAUDE.md status.
