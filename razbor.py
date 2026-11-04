"""Помощник по вакансиям — запуск из командной строки.

    python3 razbor.py help        — список команд
    python3 razbor.py             — разобрать новые вакансии и обновить сводку

Вся логика — в пакете vacancy_assistant (его же будет использовать окно программы).
"""
from vacancy_assistant.cli import main

if __name__ == "__main__":
    main()
