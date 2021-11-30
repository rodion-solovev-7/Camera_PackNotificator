import abc
import asyncio
import time
from threading import Lock
from typing import Optional

import cv2
import numpy as np
from tensorflow.lite.python.interpreter import Interpreter

from ._methods import get_neuronet_score, get_mog2_foreground_score
from ..network_sources import Sensor


class BaseDetector(metaclass=abc.ABCMeta):
    """
    Базовый абстрактный класс для всех распознавателей с изображений
    """

    # TODO: подумать над более оптимальным доступом к данным для различных компонентов
    async def update(self):
        """
        Обновляет данные с помощью асинхрона
        (для детекторов, которые не используют изображения)
        """

    @abc.abstractmethod
    def is_detected(self, image: np.ndarray) -> bool:
        """
        Получает текущую оценку изображения по критерию
        """


class NeuronetDetector(BaseDetector):
    """
    Определитель наличия пачки на изображении. Получает предсказания от нейросети.

    **Осторожно: очень медленно работает**

    Parameters:
        model_path: путь к ``TF-Lite Flatbuffer`` файлу
        threshold_score: пороговое значение для активации критерия

    Attributes:
        _THRESHOLD_SCORE: пороговое значение, меньше которого
            ``is_detected`` будет возвращать ``False``
    """
    def __init__(
            self,
            *,
            model_path: str,
            threshold_score: float = 0.6,
            pooling_period_sec: float = 0.5,
    ):
        self._interpreter = Interpreter(model_path=model_path)
        self._interpreter.allocate_tensors()

        self._THRESHOLD_SCORE = threshold_score

        self._POOLING_PERIOD_SEC = pooling_period_sec
        self._last_pooling_time = time.monotonic() - pooling_period_sec

        self._recognized = False

    async def update(self):
        """НИЧЕГО НЕ ДЕЛАЕТ"""

    def is_detected(self, image: np.ndarray) -> bool:
        """
        Определяет, есть ли на изображении пачка.
        Если предыдущая проверка была недавно, то возвращает её результат.
        """
        if time.monotonic() - self._last_pooling_time > self._POOLING_PERIOD_SEC:
            self._last_pooling_time = time.monotonic()
            score = get_neuronet_score(self._interpreter, image)
            self._recognized = score > self._THRESHOLD_SCORE
        return self._recognized


# TODO: починить код ниже от засветов (либо SaturationFilter, либо своя нейросеть) или удалить

class BackgroundDetector(BaseDetector):
    """
    Распознаватель пачек, посредством сравнения с фоном.
    Усредняет несколько последних результатов распознавания и даёт результат на их основании.
    """
    _ACTIVATION_COUNT: int
    _DEACTIVATION_COUNT: int
    _THRESHOLD_SCORE: float
    _LEARNING_RATE: float
    _SIZER: Optional[float]
    _REGION: tuple[float, float, float, float]
    _recognized: bool
    _recognize_counter: int
    _mog2: cv2.BackgroundSubtractorMOG2

    def __init__(
            self,
            *,
            background: np.ndarray = None,
            activation_interval: tuple[int, int] = (15, -20),
            learning_rate: float = 1e-4,
            threshold_score: float = 0.8,
            size_multiplier: float = 1.0,
    ):
        self._ACTIVATION_COUNT = max(activation_interval)
        self._DEACTIVATION_COUNT = min(activation_interval)
        self._THRESHOLD_SCORE = threshold_score
        self._LEARNING_RATE = learning_rate
        self._SIZER = size_multiplier
        self._REGION = (0, 0, 1, 1)

        self._recognized = False
        self._recognize_counter = 0

        self._mog2 = cv2.createBackgroundSubtractorMOG2(detectShadows=True)
        if background is not None:
            _ = self._has_foreground(background)

    async def update(self):
        """НИЧЕГО НЕ ДЕЛАЕТ"""

    def is_detected(self, image: np.ndarray) -> bool:
        recognized = self._has_foreground(image)
        if recognized:
            self._recognize_counter = max(self._recognize_counter, 0) + 1
        else:
            self._recognize_counter = min(self._recognize_counter, 0) - 1

        if self._recognize_counter >= self._ACTIVATION_COUNT:
            self._recognized = True
        elif self._recognize_counter <= self._DEACTIVATION_COUNT:
            self._recognized = False

        # удержание в диапазоне
        self._recognize_counter = max(self._recognize_counter, self._DEACTIVATION_COUNT)
        self._recognize_counter = min(self._recognize_counter, self._ACTIVATION_COUNT)

        return self._recognized

    def _has_foreground(self, image: np.ndarray) -> bool:
        image = self._get_region_from_image(image, self._REGION)
        if abs(self._SIZER - 1.0) > 1e-4:
            image = cv2.resize(image, None, fx=self._SIZER, fy=self._SIZER)
        learning_rate = self._LEARNING_RATE * (not self._recognized)
        score = get_mog2_foreground_score(image, self._mog2, learning_rate=learning_rate)
        return score > self._THRESHOLD_SCORE

    @staticmethod
    def _get_region_from_image(
            image: np.ndarray,
            region: tuple[float, float, float, float],
    ) -> np.ndarray:
        w, h = image.shape[:2][::-1]
        x1, y1, x2, y2 = region
        x1, y1, x2, y2 = map(int, (x1 * w, y1 * h, x2 * w, y2 * h))
        return image[y1:y2, x1:x2]


class SensorDetector(BaseDetector):
    """
    Определение наличия пачки посредством SNMP-запросов к датчику расстояния
    """

    def __init__(self, *, sensor: Sensor, pooling_period_sec: float = 0.5):
        self._sensor = sensor

        self._POOLING_PERIOD_SEC = pooling_period_sec

        self._recognized = False

        # TODO: переработать механизм обновления данных для избавления от блокировок
        self._lock = Lock()

    async def update(self):
        """
        Регулярно получает актуальные данные от сенсора и устанавливает recognized-флаг
        """
        while True:
            status = await self._sensor.get_sensor_status()

            if status is not None:
                with self._lock:
                    self._recognized = status

            await asyncio.sleep(self._POOLING_PERIOD_SEC)

    def is_detected(self, _: np.ndarray) -> bool:
        """
        Определяет наличие пачки через сенсор, игнорируя изображение.
        Если предыдущая проверка была недавно, то возвращает её результат.
        """
        with self._lock:
            return self._recognized
