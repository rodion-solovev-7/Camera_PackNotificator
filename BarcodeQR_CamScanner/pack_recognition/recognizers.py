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
from tensorflow.lite.python.interpreter import Interpreter

from ._evaluation_methods import (get_neuronet_score, get_mog2_foreground_score)


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
        threshold_value: пороговое значение для активации критерия

    Attributes:
        _THRESHOLD_SCORE: пороговое значение, меньше которого
            ``is_recognized`` будет возвращать ``False``
    """
    _interpreter: Interpreter
    _THRESHOLD_SCORE: float
    _image: Optional[np.ndarray]

    def __init__(self, model_path: str, threshold_value: float = 0.6):
        self._THRESHOLD_SCORE = threshold_value
        self._interpreter = Interpreter(model_path=model_path)

    def is_recognized(self, image: np.ndarray) -> bool:
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
    _learning_rate: float
    _recognized: bool
    _recognize_counter: int
    _mog2: cv2.BackgroundSubtractorMOG2

    def __init__(
            self,
            background: np.ndarray = None,
            borders: tuple[int, int] = (15, -20),
            learning_rate: float = 1e-4,
            threshold_score: float = 0.3,
    ):

        self._ACTIVATION_COUNT = max(borders)
        self._DEACTIVATION_COUNT = min(borders)
        self._THRESHOLD_SCORE = threshold_score

        self._learning_rate = learning_rate
        self._recognized = False
        self._recognize_counter = 0

        self._mog2 = cv2.createBackgroundSubtractorMOG2(detectShadows=True)
        if background is not None:
            self._mog2.apply(background, learningRate=1.0)

    def is_recognized(self, image: np.ndarray) -> bool:
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
        learning_rate = self._learning_rate * (not self._recognized)
        score = get_mog2_foreground_score(self._mog2, image, learning_rate)
        return score > self._THRESHOLD_SCORE
