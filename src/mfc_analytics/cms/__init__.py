"""Пакет интеграции с Avaya CMS."""

from mfc_analytics.cms.matcher import CallCMSMatcher
from mfc_analytics.cms.parser import AvayaCMSParser

__all__ = ["AvayaCMSParser", "CallCMSMatcher"]
