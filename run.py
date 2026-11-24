"""Скрипт запуска веб-платформы аналитики звонков контакт-центра МФЦ РУДН."""

import sys
from pathlib import Path
import uvicorn

# Добавляем src в PYTHONPATH
src_dir = Path(__file__).parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))


def main():
    print("=" * 70)
    print("  МФЦ РУДН — Интеллектуальная аналитика звонков контакт-центра")
    print("=" * 70)
    print("  Сервер запускается по адресу: http://127.0.0.1:8000")
    print("  Документация OpenAPI Swagger: http://127.0.0.1:8000/docs")
    print("  Для остановки нажмите Ctrl+C")
    print("=" * 70)
    
    uvicorn.run("mfc_analytics.api.app:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
