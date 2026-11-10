/**
 * One definition per line name, shared by the body editor and the garment editor (docs/03), so a garment
 * line is marked at the same place as the body line it is paired with by the try-on engine.
 */
export const LINE_HINTS: Record<string, string> = {
  head_top: 'Bosh tepasi: boshning eng yuqori nuqtasi.',
  neck: 'Boʻyin: iyakdan pastdagi eng ingichka joy, yelka muskuli boshlanishidan yuqorida.',
  shoulder: 'Yelka: qiya chiziq tik chiziqqa oʻtadigan yelka uchi.',
  armpit: 'Qoʻltiq: qoʻllar tanadan ajraladigan birinchi qator.',
  chest: 'Koʻkrak: eng toʻla (eng keng) joy.',
  waist: 'Bel: eng ingichka joy.',
  hip: 'Son: bel pastidagi eng keng joy.',
  crotch: 'Qoʻshilish: oyoqlar ajraladigan joy.',
  knee: 'Tizza: har bir oyoq alohida, tizza boʻgʻimi markazi.',
  ankle: 'Toʻpiq: oyoqning eng ingichka joyi, poyabzaldan yuqorida.',
  foot_bottom: 'Oyoq tagi: gavdaning eng pastki qatori.',
  hem: 'Pastki chet: kiyimning eng pastki cheti.',
  sleeve_end: 'Yeng uchi: yengning eng chetki nuqtasi.',
}

export const hintFor = (lineId: string): string => LINE_HINTS[lineId] ?? ''
