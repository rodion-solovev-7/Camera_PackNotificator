"""
Классы для распознавания различных явлений и критериев на изображениях.

Например:
    - движение
    - отличие предыдущего кадра от следующего
    - отличие изображения от эталона
    - отличие картинки от фона последних изображений
    - и т.п.
"""
import abc
from typing import Optional

import cv2
import numpy as np
import pysnmp.hlapi as snmp
from tensorflow.lite.python.interpreter import Interpreter

from ._evaluation_methods import (get_neuronet_score, get_mog2_foreground_score)
from ..image_utils import get_resized

__all__ = [
    'BaseRecognizer', 'NeuronetPackRecognizer',
    'BSPackRecognizer', 'SensorPackRecognizer',
]


class BaseRecognizer(metaclass=abc.ABCMeta):
    """
    Базовый абстрактный класс для всех распознавателей с изображений
    """

    @abc.abstractmethod
    def is_recognized(self, image: np.ndarray) -> bool:
        """
        Получает текующую оценку изображения по критерию
        """


class NeuronetPackRecognizer(BaseRecognizer):
    """
    Определитель наличия пачки на изображении. Получает предсказания от нейросети.

    **Осторожно: очень медленно работает**

    Parameters:
        model_path: путь к ``TF-Lite Flatbuffer`` файлу
        threshold_score: пороговое значение для активации критерия

    Attributes:
        _THRESHOLD_SCORE: пороговое значение, меньше которого
            ``is_recognized`` будет возвращать ``False``
    """
    _THRESHOLD_SCORE: float
    _interpreter: Interpreter

    def __init__(self, *, model_path: str, threshold_score: float = 0.6):
        self._THRESHOLD_SCORE = threshold_score
        self._interpreter = Interpreter(model_path=model_path)
        self._interpreter.allocate_tensors()
        self._SKIPFRAME_MOD = 15
        self._skipframe_counter = self._SKIPFRAME_MOD + 1
        self._recognized = False

    def is_recognized(self, image: np.ndarray) -> bool:
        self._skipframe_counter = (self._skipframe_counter + 1) % self._SKIPFRAME_MOD
        if self._skipframe_counter == 0:
            self._recognized = self._has_pack(image)
        return self._recognized

    def _has_pack(self, image: np.ndarray):
        score = get_neuronet_score(self._interpreter, image)
        return score > self._THRESHOLD_SCORE


class BSPackRecognizer(BaseRecognizer):
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
            activation_interval: dict[str, int] = (15, -20),
            learning_rate: float = 1e-4,
            threshold_score: float = 0.8,
            size_multiplier: float = 1.0,
            region: dict[str, float] = None,
    ):
        region = dict(x1=0, x2=1, y1=0, y2=1) if region is None else region

        self._ACTIVATION_COUNT = activation_interval['upper_bound']
        self._DEACTIVATION_COUNT = activation_interval['lower_bound']
        self._THRESHOLD_SCORE = threshold_score
        self._LEARNING_RATE = learning_rate
        self._SIZER = size_multiplier
        self._REGION = (region['x1'], region['y1'], region['x2'], region['y2'])

        self._recognized = False
        self._recognize_counter = 0

        self._mog2 = cv2.createBackgroundSubtractorMOG2(detectShadows=True)
        if background is not None:
            _ = self._has_foreground(background)

    def is_recognized(self, image: np.ndarray) -> bool:
        # TODO: брать только нижнюю часть изображения (прокинуть регион в конструктор)
        recognized = self._has_foreground(image)
        if recognized:
            self._recognize_counter = max(self._recognize_counter, 0) + 1
        else:
            self._recognize_counter = min(self._recognize_counter, 0) - 1

        if self._recognize_counter >= self._ACTIVATION_COUNT:
            self._recognized = True
        elif self._recognize_counter <= self._DEACTIVATION_COUNT:
            self._recognized = False

        # нормализация в диапазоне
        self._recognize_counter = max(self._recognize_counter, self._DEACTIVATION_COUNT)
        self._recognize_counter = min(self._recognize_counter, self._ACTIVATION_COUNT)

        return self._recognized

    def _has_foreground(self, image: np.ndarray) -> bool:
        image = self._get_region_from_image(image, self._REGION)
        if abs(self._SIZER - 1.0) > 1e-4:
            image = get_resized(image, sizer=self._SIZER)
        learning_rate = self._LEARNING_RATE * (not self._recognized)
        score = get_mog2_foreground_score(self._mog2, image, learning_rate)
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


class SensorPackRecognizer(BaseRecognizer):
    """
    Определение наличия пачки посредством SNMP-запросов к датчику расстояния
    """
    # TODO: возможно стоит вынести блокирующие запросы в асинхронный процесс
    #  и обеспечить связь данного класса с процессом через очередь для исключения блокировок

    def __init__(self, *, sensor_ip: str, sensor_key: str):
        # TODO: убрать костанты и сделать нормальную расширяемость
        #  добавить усреднение результата и другие
        self._SKIPFRAME_MOD = 15
        self._skipframe_counter = self._SKIPFRAME_MOD + 1
        self._recognized = False
        self._snmp_detector_ip = sensor_ip
        self._snmp_engine = snmp.SnmpEngine()
        self._snmp_community_string = 'public'
        self._snmp_sensor_identity = snmp.ObjectIdentity(sensor_key)
        self._snmp_port = 161
        self._snmp_context = snmp.ContextData()

    def is_recognized(self, _: np.ndarray) -> bool:
        self._skipframe_counter = (self._skipframe_counter + 1) % self._SKIPFRAME_MOD
        if self._skipframe_counter == 0:
            self._recognized = self._has_pack()
        return self._recognized

    def _has_pack(self) -> bool:
        erd = self._snmp_get()
        return bool(erd)

    def _snmp_get(self) -> str:
        """получение состояния"""
        t = snmp.getCmd(
            self._snmp_engine,
            snmp.CommunityData(self._snmp_community_string),
            snmp.UdpTransportTarget((self._snmp_detector_ip, self._snmp_port)),
            self._snmp_context,
            snmp.ObjectType(self._snmp_sensor_identity),
        )
        errorIndication, errorStatus, errorIndex, varBinds = next(t)
        for name, val in varBinds:
            return val.prettyPrint()
