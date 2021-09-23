"""
Модели для обмена данными между компонентами программы
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

__all__ = [
    'CameraProcessEvent', 'CameraPackResult', 'EndScanning', 'PackGoodCodes',
    'PackBadCodes', 'ValidatedPack',
]


@dataclass
class CameraProcessEvent:
    """События, создаваемые при обработке видео"""
    worker_id: int = -1


@dataclass
class EndScanning(CameraProcessEvent):
    """
    Завершение сканирования.

    (Возможно стоит убить или перезапустить процесс или завершить работу скрипта)
    """
    message: str = "Сканирование завершено"


@dataclass
class CameraPackResult(CameraProcessEvent):
    """
    Информация о пачке от процесса-обработчика видео.
    Содержит worker-id время появления пачки и её ухода,
    считанные пары QR-кодов и штрихкодов.
    """
    start_time: Optional[datetime] = None
    finish_time: Optional[datetime] = None
    codepairs: list[dict[str, str]] = field(default_factory=list)
    expected_codes_count: int = 2
    workmode: str = 'auto'

    def __repr__(self) -> str:
        if self.start_time is not None:
            start = self.start_time.strftime('%m-%d_%H:%M:%S')
        else:
            start = 'EMPTY'
        if self.finish_time is not None:
            finish = self.finish_time.strftime('%m-%d_%H:%M:%S')
        else:
            finish = 'EMPTY'
        time_interval = f"{start} - {finish}"
        return f"<{self.__class__.__name__} {time_interval} {self.codepairs}>"


@dataclass
class ValidatedPack:
    """
    Базовый класс для всех провалидированных результатов
    """


@dataclass
class PackGoodCodes(ValidatedPack):
    """
    Обработанный провалидированный результат,
    содержащий все необходимые коды в нужном кол-ве.

    Готово к отправке на сервер.
    """
    codepairs: list[dict[str, str]] = field(default_factory=list)


@dataclass
class PackBadCodes(ValidatedPack):
    """
    Обработанный результат, не прошедший валидацию.

    Готово к отправке на сервер.
    """
    codepairs: list[dict[str, str]] = field(default_factory=list)
