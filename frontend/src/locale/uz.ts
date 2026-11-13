/**
 * Uzbek UI strings for the garment landmark editor (the one locale file; more screens move here over time).
 * Group names and check messages are the same strings as backend apps/garments/landmark_checks.py
 * (GROUP_NAMES, MESSAGES, WARNINGS), so a client error and a server error read the same.
 */

export const GARMENT_GROUP_NAMES = {
  tshirt: {
    collar: 'Yoqa',
    shoulder: 'Yelka',
    collar_bottom: 'Yoqa pasti',
    armpit: 'Qoʻltiq',
    sleeve_cuff_outer: 'Yeng uchi (tashqi)',
    sleeve_cuff_inner: 'Yeng uchi (ichki)',
    chest: 'Koʻkrak',
    waist: 'Bel',
    hem: 'Pastki',
    neck_hole: 'Yoqa teshigi',
  },
  pants: { waist: 'Bel', hip: 'Son', crotch: 'Qoʻshilish', knee: 'Tizza', hem: 'Pocha' },
} as const

/** Point label suffixes: image left / right / centre. */
export const SIDE = { left: 'Sol', right: 'Oʻng', center: 'Markaz' } as const

const q = (g: string) => `«${g}»`

export const CHECK_MESSAGES = {
  x_order: (g: string) => `${q(g)}: chap nuqta oʻng nuqtadan chapda boʻlsin.`,
  center: (g: string) => `${q(g)}: markaz nuqtasi chap va oʻng nuqtalar orasida boʻlsin.`,
  y_order: (g: string, other: string) => `${q(g)} chizigʻi ${q(other)} chizigʻidan pastda boʻlsin.`,
  cuff_side: (g: string) => `${q(g)}: chap yeng nuqtasi rasmning chap yarmida, oʻngi oʻng yarmida boʻlsin.`,
  cuff_order: (g: string) =>
    `${q(g)}: tashqi nuqta yengning tashqi (yelka) tomonida, ichki nuqta qoʻltiq tomonida boʻlsin.`,
  // neck_hole polygon (docs/09 #102), same strings as backend MESSAGES hole_* / bounds
  bounds: (g: string) => `${q(g)} nuqtasi rasm chegarasidan chiqib ketgan.`,
  hole_points: (g: string) => `${q(g)}: 3 tadan 64 tagacha nuqta boʻlsin.`,
  hole_self: (g: string) => `${q(g)} chizigʻi oʻzini kesib oʻtmasin.`,
  hole_empty: (g: string) => `${q(g)} yuzasi boʻsh. Nuqtalarni yoqa ichki cheti boʻylab qoʻying.`,
  hole_area: (g: string) => `${q(g)} juda katta: kiyim yuzasining 25 % idan oshmasin.`,
  hole_top: (g: string) => `${q(g)} nuqtalari kiyimning yuqori qismida (balandlikning 40 % ida) boʻlsin.`,
}

export const CHECK_WARNINGS = {
  collar_far: (g: string) => `${q(g)} nuqtalari yelka chizigʻidan uzoq. Yoqa chetlarini yelka chizigʻida belgilang.`,
  outside_garment: (g: string) => `${q(g)} nuqtasi kiyimdan tashqarida. Nuqtani kiyim ustiga qoʻying.`,
  chest_above_armpit: (g: string, other: string) =>
    `${q(g)} chizigʻi ${q(other)} chizigʻidan yuqorida. Keng (oversize) kiyimda bu odatiy holat, aks holda nuqtalarni tekshiring.`,
}

export const LANDMARK_EDITOR = {
  incompleteBanner: (missing: string[]) =>
    `Bu kiyimda yangi belgi nuqtalari yetishmayapti: ${missing.join(', ')}. ` +
    'Iltimos, ularni belgilab, qayta saqlang.',
  optionalCount: (placed: number, total: number) => `+ ${placed} / ${total} qoʻshimcha`,
  checksTitle: 'Tekshiruv',
  warningsTitle: 'Eslatma',
  step: (n: number, total: number) => `${n} / ${total}`,
  next: 'Keyingi',
  save: 'Saqlash',
  saving: 'Saqlanmoqda…',
  back: '← Orqaga',
}

/** Garment editor step 2 (T-shirts): collar points + the neckline hole polygon (docs/09 #102, docs/10 screen 9). */
export const NECK_EDITOR = {
  heading: 'Yoqa va boʻyin teshigi · Futbolka',
  subheading: 'Avval yoqaning 3 nuqtasini qoʻying, keyin yoqa teshigini toʻgʻrilang.',
  polygonTitle: 'Yoqa teshigi',
  polygonHint:
    'Teshik yoqa bandining ICHKI cheti boʻylab oʻtsin va kiyimning eng yuqori chetigacha chiqsin: ' +
    'orqa tomonning ichki qismi (yorliq ham) teshik ichida qolsin. Band oʻzi teshikdan tashqarida boʻlsin.',
  polygonWaiting: 'Yoqa teshigi yoqaning 3 nuqtasi qoʻyilgach chiziladi.',
  polygonHelp: 'Nuqtani suring. Chiziq ustiga bosing: yangi nuqta. Tanlangan nuqtani oʻchirish mumkin (kamida 3 ta).',
  pointsModeHelp: 'Yoqa nuqtalarini surganda teshik oʻzgarmaydi. Yangi nuqtalardan qayta chizish uchun shaklni tanlang.',
  modeLabel: 'Nimani tahrirlash',
  modePoints: 'Yoqa nuqtalari',
  modeHole: 'Yoqa teshigi',
  shapeLabel: 'Yoqa shakli',
  shapes: { v: 'V', round: 'Dumaloq', square: 'Toʻrtburchak' },
  polygonCount: (n: number) => `${n} nuqta`,
  deleteVertex: 'Nuqtani oʻchirish',
  resetPolygon: 'Qayta tiklash',
  skip: 'Oʻtkazib yuborish',
  skipHint: 'Oʻtkazib yuborsangiz, boʻyin atrofi yomonroq koʻrinishi mumkin. Keyinroq qaytib belgilash mumkin.',
  needStep1: 'Avval 1-qadamdagi asosiy nuqtalarni belgilang.',
  goStep1: '1-qadamga oʻtish',
  saved: 'Muvaffaqiyatli saqlandi',
  vertexLabel: (i: number) => `Yoqa teshigi nuqtasi ${i + 1}`,
}

/** Garment card chips (Wardrobe). */
export const GARMENT_CHIPS = {
  neckUnmarked: 'Boʻyin belgilanmagan',
}

/** Try-on job result quality warnings (job.result.quality_warnings). */
export const TRYON_QUALITY: Record<string, string> = {
  neck_hole_invalid: 'Yoqa teshigi notoʻgʻri belgilangan, shu sababli hisobga olinmadi. Kiyimning yoqasini qayta belgilang.',
  mls_fallback: 'Kiyim uchun barcha nuqtalar topilmadi, oddiy usulda kiydirildi.',
}

/** Garment settings (screen 9) and list badges/filters (docs/09 #93). */
export const GARMENT_SETTINGS = {
  fitTitle: 'Moslashish',
  fit: { adapt: 'Tanaga moslash', keep_shape: 'Kiyim shaklini saqlash' },
  fitHelp: {
    adapt: 'Kiyim tananing nuqtalariga toʻliq moslashadi.',
    keep_shape: 'Kiyim oʻz shaklini saqlaydi (keng, oversize). Hozircha natija «Tanaga moslash» bilan bir xil.',
  },
  genderTitle: 'Kim uchun',
  gender: { female: 'Ayollar', male: 'Erkaklar', unisex: 'Uniseks' },
  genderFilterAll: 'Hammasi',
  saved: 'Saqlandi',
  saveError: 'Saqlab boʻlmadi. Qayta urinib koʻring.',
} as const

/** Garment gender in try-on (docs/09 #97): male base -> male + unisex, female base -> female + unisex. */
export const SEX_LABELS = { male: 'Erkak', female: 'Ayol' } as const

export const TRYON_GENDER = {
  showAll: 'Barcha kiyimlarni koʻrsatish',
  otherGender: 'Boshqa jins uchun',
  filteredFor: (sex: string) => `${sex} uchun mos kiyimlar (va uniseks)`,
  pickBaseFirst: 'Avval asos tanlang: kiyimlar unga mos ravishda saralanadi.',
  mismatch: 'Tanlangan kiyim boshqa jins uchun moʻljallangan. Mos kiyim yoki boshqa asos tanlang.',
  bodySexTitle: 'Tanangiz jinsi',
  bodySexHelp: 'Kiyimlarni saralash uchun bir marta tanlang. Keyin oʻzgartirib boʻlmaydi.',
  bodySexRequired: 'Avval tanangiz jinsini tanlang.',
  noMatching: 'Bu asos uchun mos kiyim yoʻq.',
} as const

export const BODY_UPLOAD = {
  sexTitle: 'Jinsingiz',
  sexHelp: 'Kiyimlar shunga qarab saralanadi. Keyin oʻzgartirib boʻlmaydi.',
  sexRequired: 'Jinsingizni tanlang.',
} as const

