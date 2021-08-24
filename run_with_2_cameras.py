"""Скрипт для запуска чтения с 2-ух камер с синхронизацией данных"""

from dotenv import load_dotenv

from BarcodeQR_CamScanner.scan_with_2_cameras import run


if __name__ == '__main__':
    load_dotenv()
    run()
