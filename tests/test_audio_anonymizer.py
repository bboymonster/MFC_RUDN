"""Тесты модуля обезличивания персональных данных по 152-ФЗ."""

from mfc_analytics.audio.anonymizer import PIIAnonymizer


def test_mask_phone_numbers():
    anonymizer = PIIAnonymizer()
    text = "Мой номер телефона +7 (925) 123-45-67 или 89169998877, перезвоните мне."
    masked, stats = anonymizer.mask_text(text)
    
    assert "+7 (925) 123-45-67" not in masked
    assert "89169998877" not in masked
    assert "[ТЕЛЕФОН_СКРЫТ]" in masked
    assert stats["phones_masked"] >= 2


def test_mask_snils_and_passports():
    anonymizer = PIIAnonymizer()
    text = "СНИЛС абитуриента: 142-883-991 70, паспорт серии 45 12 номер 123456."
    masked, stats = anonymizer.mask_text(text)
    
    assert "142-883-991 70" not in masked
    assert "123456" not in masked
    assert "[СНИЛС_СКРЫТ]" in masked
    assert "[ПАСПОРТ_СКРЫТ]" in masked
    assert stats["snils_masked"] >= 1
    assert stats["passports_masked"] >= 1


def test_generate_pseudonym():
    anonymizer = PIIAnonymizer()
    p1 = anonymizer.generate_pseudonym("+79251234567")
    p2 = anonymizer.generate_pseudonym("+79251234567")
    p3 = anonymizer.generate_pseudonym("+79990001122")
    
    # Устойчивость и детерминированность
    assert p1 == p2
    assert p1 != p3
    assert p1.startswith("Заявитель_")
