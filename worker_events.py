from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class CamScannerEvent:
    """Базовый класс для хранения данных события от  worker-процесса"""
    worker_id: Optional[int] = None
    start_time: Optional[datetime] = None
    receive_time: Optional[datetime] = None
    finish_time: Optional[datetime] = None


@dataclass
class TaskError(CamScannerEvent):
    """Информация об ошибке из worker-процесса"""
    error_message: Optional[str] = None


@dataclass
class TaskResult(CamScannerEvent):
    """Информация об успешном считывании QR- и штрихкода"""
    qr_code: Optional[str] = None
    barcode: Optional[str] = None
