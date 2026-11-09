from rest_framework import serializers
from .models import Job

ERROR_MESSAGES = {
    "NOT_FULL_BODY": "To'liq bo'y tushing: bosh va oyoqlar kadrda bo'lsin.",
    "NOT_FRONT_FACING": "Kameraga old tomoningiz bilan turing.",
    "NOT_UPRIGHT": "Tik turing.",
    "ARMS_NOT_AWAY": "Qo'llaringizni tanadan biroz uzoqroq oching.",
    "LEGS_NOT_APART": "Oyoqlaringizni yelka kengligida oching.",
    "LONG_SLEEVES": "Kalta yengli yoki yengsiz kiyimda tushing (yeng tirsakdan yuqorida tugasin).",
    "LOOSE_OR_THICK_CLOTHING": "Qalin yoki keng kiyim aniqlandi. Tor sport kiyimida qayta tushing.",
    "MULTIPLE_PEOPLE": "Rasmda faqat siz bo'lishingiz kerak.",
    "NO_PERSON": "Rasmda odam topilmadi.",
    "POOR_LIGHTING": "Yoru'g'roq joyda, aniq rasm tushing.",
    "NOT_A_REAL_PHOTO": "Haqiqiy fotosurat yuklang.",
    "APPARENT_MINOR": "Bu rasmni qabul qila olmaymiz. Boshqa rasm yuklab ko'ring.",
    "NO_GARMENT": "Rasmda kiyim topilmadi.",
    "WRONG_TYPE": "Tanlangan tur rasmdagi kiyimga mos emas. Hozircha faqat futbolka va shim qabul qilinadi.",
    "NOT_FRONT_VIEW": "Kiyimning old tomonini yuklang.",
    "GARMENT_CUT_OFF": "Kiyim to'liq ko'rinsin, chetlari kesilmasin.",
    "LOW_QUALITY": "Rasm xira yoki kichik. Aniqroq rasm yuklang.",
    "FILE_TOO_LARGE": "Fayl hajmi juda katta. 20 MB dan kichik rasm yuklang.",
    "BAD_FILE_TYPE": "Faqat JPG yoki PNG formatidagi rasmlar qabul qilinadi.",
    "AI_FAILED": "Tekshiruv vaqtida xatolik yuz berdi. Qayta urinib ko'ring.",
    "AI_UNAVAILABLE": "Tekshiruv xizmati hozircha ishlamayapti. Keyinroq qayta urinib koʻring.",
    "INVALID_AI_RESPONSE": "Rasmni tekshirib boʻlmadi. Boshqa rasm yuklab koʻring.",
    "CLEAN_FAILED": "Kiyimni tozalab boʻlmadi. Boshqa rasm yuklab koʻring.",
    "WARP_FAILED": "Kiyimni tanaga moslashtirib boʻlmadi. Qayta urinib koʻring.",
    "BODY_NOT_FOUND": "Tana topilmadi.",
    "GARMENT_NOT_FOUND": "Kiyim topilmadi.",
}


class JobSerializer(serializers.ModelSerializer):
    error_message = serializers.SerializerMethodField()

    class Meta:
        model = Job
        fields = ("id", "kind", "status", "result", "error_code", "error_message", "created_at", "updated_at")

    def get_error_message(self, obj):
        if obj.error_code:
            return ERROR_MESSAGES.get(obj.error_code, obj.error_detail or "Noma'lum xatolik.")
        return None
