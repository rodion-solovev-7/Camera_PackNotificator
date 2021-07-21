from logging import NOTSET, ERROR, DEBUG, INFO
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class CamScannerEvent:
    """Базовый класс для хранения данных события от worker-процесса"""
    LOG_LEVEL: int = field(default=NOTSET, repr=False)

    worker_id: Optional[int] = None
    start_time: Optional[datetime] = None
    receive_time: Optional[datetime] = None
    finish_time: Optional[datetime] = None


@dataclass
class TaskError(CamScannerEvent):
    """Информация об ошибке из worker-процесса"""
    LOG_LEVEL = ERROR

    message: Optional[str] = None


@dataclass
class TaskResult(CamScannerEvent):
    """Информация о считывании QR- и штрихкода"""
    LOG_LEVEL = DEBUG

    qr_code: Optional[str] = None
    barcode: Optional[str] = None


@dataclass
class EndScanning(CamScannerEvent):
    """Завершение сканирования"""
    LOG_LEVEL = INFO

    message: Optional[str] = None


@dataclass
class StartScanning(CamScannerEvent):
    """Начало сканирования"""
    LOG_LEVEL = INFO

    message: Optional[str] = None
