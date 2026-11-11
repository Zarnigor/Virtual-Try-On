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

