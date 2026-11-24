"""Модуль обезличивания и защиты персональных данных в соответствии с 152-ФЗ."""

import hashlib
import re
from typing import Dict, List, Tuple


class PIIAnonymizer:
    """Обезличиватель чувствительных данных заявителей и операторов."""

    # 1. Телефоны: +7..., 8..., в том числе сплошные 11 цифр 89XXXXXXXXX / 79XXXXXXXXX
    PHONE_REGEX = re.compile(
        r"(?:\+7|8)[\s\-]?(?:\(?\d{3}\)?[\s\-]?)?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}\b|\b(?:8|7)\d{10}\b"
    )
    # 2. СНИЛС: XXX-XXX-XXX XX или фраза со СНИЛС
    SNILS_REGEX = re.compile(
        r"\b\d{3}[\s\-]\d{3}[\s\-]\d{3}[\s\-]\d{2}\b|(?:снилс\D{0,5})\b\d{11}\b",
        re.IGNORECASE
    )
    # 3. Паспорта РФ: серия 4 цифры (или 2+2) и номер 6 цифр, возможно со словами серия/номер
    PASSPORT_REGEX = re.compile(
        r"(?:сери[яи]\s*)?\b\d{2}\s?\d{2}\b(?:\s*номер\s*|\s*N\s*|\s+)\b\d{6}\b|\b\d{4}\s\d{6}\b",
        re.IGNORECASE
    )
    # 4. Email
    EMAIL_REGEX = re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
    )

    def mask_text(self, text: str) -> Tuple[str, Dict[str, int]]:
        """Маскирует чувствительные персональные данные в тексте."""
        stats = {
            "phones_masked": 0,
            "snils_masked": 0,
            "passports_masked": 0,
            "emails_masked": 0,
        }

        # 1. Сначала форматированный СНИЛС (XXX-XXX-XXX XX)
        def _replace_snils(m):
            stats["snils_masked"] += 1
            return "[СНИЛС_СКРЫТ]"

        # 2. Телефоны
        def _replace_phone(m):
            stats["phones_masked"] += 1
            return "[ТЕЛЕФОН_СКРЫТ]"

        # 3. Паспорта
        def _replace_passport(m):
            stats["passports_masked"] += 1
            return "[ПАСПОРТ_СКРЫТ]"

        # 4. Email
        def _replace_email(m):
            stats["emails_masked"] += 1
            return "[EMAIL_СКРЫТ]"

        # Порядок замены: сначала специфичный СНИЛС с дефисами/пробелами, затем паспорта, телефоны, email
        masked = self.SNILS_REGEX.sub(_replace_snils, text)
        masked = self.PASSPORT_REGEX.sub(_replace_passport, masked)
        masked = self.PHONE_REGEX.sub(_replace_phone, masked)
        masked = self.EMAIL_REGEX.sub(_replace_email, masked)

        return masked, stats

    @staticmethod
    def generate_pseudonym(raw_identifier: str, prefix: str = "Заявитель") -> str:
        """Создает устойчивый необратимый псевдоним (хэш) для идентификатора заявителя."""
        clean_id = re.sub(r"\D", "", raw_identifier) or raw_identifier
        salt = "mfc_rudn_salt_2026"
        h = hashlib.sha256((clean_id + salt).encode("utf-8")).hexdigest()[:6]
        return f"{prefix}_{h}"
