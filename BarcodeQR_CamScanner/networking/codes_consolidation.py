"""
Очереди обработки результатов от камер.

TODO: нужно адекватное описание роли компонента в программе
"""
import abc
from collections import deque

from loguru import logger

from ..models import (CameraPackResult, PackBadCodes, PackGoodCodes, ValidatedPack)
from ..scanning.code_reading import CodeType


class BaseResultConsolidationQueue(metaclass=abc.ABCMeta):
    """
    Базовый абстрактный класс очередей синхронизации для данных с пачек
    """

    @abc.abstractmethod
    def enqueue(self, result: CameraPackResult) -> None:
        """
        Добавление результата в очередь для дальнейшей обработки
        """

    @abc.abstractmethod
    def get_processed_latest(self) -> list[ValidatedPack]:
        """
        Синхронизирует последние результаты из очереди
        и возвращает список с результатами их синхронизации
        """


class ResultValidator(BaseResultConsolidationQueue):
    """
    Очередь для обработки результатов с одной камеры.
    Хранит, валидирует результаты и возвращает соответствующие данные.

    Автоматически дописывает недостающие QR-коды заглушками вроде ``empty_0_2001-04-01``.
    Штрих-коды дописываются заглушкой ``000...000`` (13 нулей).
    """
    _queue: deque[CameraPackResult]
    _blacklisted_qrs: set[str] = {'xps.tn.ru'}

    def __init__(self):
        self._queue = deque()

    def enqueue(self, result: CameraPackResult) -> None:
        """
        Добавляет запись в очередь для обработки.
        """
        self._queue.append(result)

    def get_processed_latest(self) -> list[ValidatedPack]:
        """
        Обрабатывает все пачки, находящиеся в очереди и
        возвращает список с их результатами.

        Для каждой пачки проверяет количество кодов, считанных с пачки.
        Если оно совпадает с ожидаемым, то возращает ``PackGoodCodes`` с кодами.
        Если количество кодов меньше ожидаемого, то вместо недостающих кодов
        добавляются заглушки и возвращается ``PackBadCodes`` с ошибкой.
        """
        processed = []

        for pack in self._queue:
            if pack.workmode != 'auto':
                logger.info(f"Из-за неавтоматического режима работы проигнорирована пачка: {pack}")
                continue

            pack.codepairs = [d for d in pack.codepairs
                              if d[CodeType.QR_CODE] not in self._blacklisted_qrs]

            expected_count = pack.expected_codes_count
            real_count = len(pack.codepairs)

            if real_count >= expected_count:
                if real_count > expected_count:
                    logger.warning(f"Считанное количество кодов ({real_count}) "
                                   f"превышает ожидаемое ({expected_count})")
                logger.info(f"Пачка {pack} помечена корректной")
                processed.append(PackGoodCodes(codepairs=pack.codepairs))
                continue

            logger.info(f"Ожидалось {pack.expected_codes_count} пар кодов, "
                        f"но с пачки считалось {real_count}")
            missed_qrcodes_count = max(0, expected_count - real_count)

            pack.codepairs += [
                {
                    CodeType.QR_CODE: '',
                    CodeType.BARCODE: '0' * 13,
                } for _ in range(1, missed_qrcodes_count + 1)
            ]
            logger.info(f"Недостающие {missed_qrcodes_count} кодов были заполнены заглушками")
            logger.info(f"Пачка {pack} помечена некорректной")

            processed.append(PackBadCodes(codepairs=pack.codepairs))

        self._queue.clear()
        return processed
