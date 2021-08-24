"""
Очереди обработки результатов от камер
"""
import abc
from collections import deque
from datetime import timedelta
from typing import Iterable

from loguru import logger

from .event_system.events import *
from .event_system.handling import BaseEvent


class BaseResultProcessingQueue(metaclass=abc.ABCMeta):
    """
    Базовый абстрактный класс для очередей синхронизации
    данных пачек из разных источников
    """

    @abc.abstractmethod
    def enqueue(self, result: CameraPackResult) -> None:
        """
        Добавление результата в очередь для дальнейшего сопоставления
        с другими результатами
        """

    @abc.abstractmethod
    def get_processed_latest(self) -> Iterable[BaseEvent]:
        """
        Синхронизирует последние результаты из очереди
        и возвращает последовательность с результатами их синхронизации
        """


class Interval2CamerasProcessingQueue(BaseResultProcessingQueue):
    """
    Очередь для синхронизации и валидации результатов от 2-ух разных камер в цельные результаты с пачек.
    Синхронизирует пачки группами, опираясь на разницу во времени.
    """

    RESULT_TIMEOUT_TIME: timedelta
    _queue: deque[CameraPackResult]

    RESULT_TIMEOUT_TIME = timedelta(seconds=20)
    """
    Время, после которого результат сопоставляется с другими,
    а затем удаляется из очереди.
    """

    def __init__(self):
        self._queue = deque()

    def enqueue(self, result: CameraPackResult) -> None:
        """
        Обрабатывает полученную от сканера запись с QR- и шрихкодами.
        Добавляет её в очередь для сопоставления.
        """
        self._queue.append(result)

    def get_processed_latest(self) -> Iterable[BaseEvent]:
        """Синхронизирует пачки с разнык камер по пересечению их временных отрезков"""
        while len(self._queue) > 0 and \
                datetime.now() - self._queue[0].finish_time > self.RESULT_TIMEOUT_TIME:
            logger.debug("Сопоставление данных с пачек")
            packs_group = self._extract_oldest_group(self._queue)

            if packs_group[0].expected_codes_count != packs_group[-1].expected_codes_count:
                logger.warning("В одной группе оказались пачки, от которых ожидается разное количество кодов")

            packs0 = list(filter(lambda p: p.worker_id == 0, packs_group))
            packs1 = list(filter(lambda p: p.worker_id == 1, packs_group))

            if len(packs0) == 0 or len(packs1) == 0:
                logger.warning("Для пачки не найдена пара (рассинхрон?)")

            qr_codes0, qr_codes1 = [], []
            barcodes0, barcodes1 = [], []

            for pack in packs0:
                barcodes0 += pack.barcodes
                qr_codes0 += pack.qr_codes
            for pack in packs1:
                barcodes1 += pack.barcodes
                qr_codes1 += pack.qr_codes

            if len(qr_codes0) == 0 and len(qr_codes1) == 0:
                yield PackBadCodes()
                continue

            if len(qr_codes0) > 0 and len(qr_codes1) > 0:
                logger.warning("После сопоставления в группе с обеих сторон оказались коды")
                yield PackBadCodes()
                continue

            barcodes = barcodes0 + barcodes1
            qr_codes = qr_codes0 + qr_codes1

            missed_barcodes_count = len(qr_codes) - len(barcodes)
            barcodes += [barcodes[-1]] * missed_barcodes_count

            if len(qr_codes) != packs_group[0].expected_codes_count:
                logger.warning(f"Ожидалось {packs_group[0].expected_codes_count} кодов, "
                               f"но в сопоставленной группе их оказалось {len(qr_codes)}")
                yield PackBadCodes()
                continue

            yield PackWithCodes(
                qr_codes=qr_codes,
                barcodes=barcodes,
            )

    @staticmethod
    def _extract_oldest_group(packs: deque[CameraPackResult]) -> list[CameraPackResult]:
        """Извлечение цепочки самых старых пачек, которые пересекались по времени"""
        if len(packs) == 0:
            return []
        group = []
        bound = packs[0].finish_time
        while len(packs) > 0 and packs[0].start_time <= bound:
            pack = packs.popleft()
            bound = max(bound, pack.finish_time)
            group.append(pack)
        return group


class InstantCameraProcessingQueue(BaseResultProcessingQueue):
    """
    Очередь для обработки результатов с одной камеры.
    Хранит, валидирует результаты и возвращает соответствующие
    """
    _queue: deque[CameraPackResult]

    def __init__(self):
        self._queue = deque()

    def enqueue(self, result: CameraPackResult) -> None:
        """
        Обрабатывает полученную от сканера запись с QR- и шрихкодами.
        Добавляет её в очередь для обработки.
        """
        self._queue.append(result)

    def get_processed_latest(self) -> list[BaseEvent]:
        """Валидирует пачки с одной камеры"""
        processed = []

        for pack in self._queue:
            qr_codes = pack.qr_codes
            barcodes = pack.barcodes

            if len(qr_codes) == 0:
                logger.debug("Пачка без QR кодов")
                processed.append(PackBadCodes())
                continue

            if len(barcodes) == 0:
                logger.debug("Пачка с QR кодами, но без штрихкодов")
                processed.append(PackBadCodes())
                continue

            missed_barcodes_count = len(qr_codes) - len(barcodes)
            barcodes += barcodes[-1:] * missed_barcodes_count

            if len(qr_codes) != pack.expected_codes_count:
                logger.debug(f"Ожидалось {pack.expected_codes_count} кодов, "
                             f"но с пачки считалось {len(qr_codes)}")
                processed.append(PackBadCodes())
                continue

            processed.append(PackWithCodes(
                qr_codes=qr_codes,
                barcodes=barcodes,
            ))

        self._queue.clear()
        return processed
