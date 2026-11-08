"""Помощник по вакансиям: поиск вакансий на hh.ru, разбор их языковой моделью по резюме и критериям
человека, сопроводительные письма и сводка.

Пакет — библиотека: функции получают профиль явно (Profile) и сообщают о ходе работы через
необязательный параметр log (по умолчанию — печать). Командная строка — vacancy_assistant.cli.
"""
__version__ = "0.5.10"         # единственное место с номером версии: его берут окно и сборка установщиков

from .errors import AssistantError
from .profile import Profile, default_profile_name

__all__ = ["AssistantError", "Profile", "default_profile_name", "__version__"]
