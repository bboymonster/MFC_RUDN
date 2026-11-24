"""Модуль данных: база знаний и генератор демонстрационных выборок."""

from mfc_analytics.data.generator import MFCDataGenerator
from mfc_analytics.data.seed_rules import DEPARTMENTS, REFERENCE_RULES

__all__ = ["MFCDataGenerator", "DEPARTMENTS", "REFERENCE_RULES"]
