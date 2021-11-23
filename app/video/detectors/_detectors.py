"""
Классы для поиска объектов на изображении.
"""
import abc
from typing import Optional

import cv2
import numpy as np

from ._detection_methods import get_object_bounds_mog2


class BasePackDetector(metaclass=abc.ABCMeta):
    """
    Базовый класс для всех распознавателей объектов.
    """

    @abc.abstractmethod
    def get_object_boxes(self, image: np.ndarray) -> list[tuple[int, int, int, int]]:
        """
        Находит позиции объектов на изображении
        """


class Mog2ObjectDetector(BasePackDetector):
    """
    Определяет позиции объектов через mog2 BackgroundSubtractor.
    """

    mog2: cv2.BackgroundSubtractorMOG2

    def __init__(self):
        self.mog2 = cv2.createBackgroundSubtractorMOG2(history=10, varThreshold=95, detectShadows=False)
        self.update_counter = 0
        self.update_counter_limit = 25
        self.background: Optional[np.ndarray] = None

    def get_object_boxes(self, image: np.ndarray) -> list[tuple[int, int, int, int]]:
        """
        Находит позиции объектов посредством вычитания фона.
        """
        if self.background is None:
            self.background = image.copy()
        self.refresh_background_or_skip()

        bounding_boxes = get_object_bounds_mog2(image, mog2=self.mog2)
        self.prepare_new_background(image, bounding_boxes)
        return bounding_boxes

    def refresh_background_or_skip(self) -> None:
        """
        Обновляет счётчик считанных кадров.
        При достижении определённого кол-ва итераций обновляет фон и сбрасывает счётчик.
        """
        if self.update_counter == 0:
            self.update(self.background)
        self.update_counter = (self.update_counter + 1) % self.update_counter_limit

    def prepare_new_background(
            self,
            image: np.ndarray,
            bounding_boxes: list[tuple[int, int, int, int]],
    ) -> None:
        """
        Обновляет фон в регионах, где объектов не обнаружено.
        """
        for box1, box2 in zip(bounding_boxes[:-1], bounding_boxes[:1]):
            x1, y1, w1, h1 = box1
            x2, y2, w2, h2 = box2

            # обновляется фрагмент фона между пачками (y-координаты игнорируются)
            self.background[:, x1 + w1: x2] = (
                (0.8 * self.background[:, x1 + w1: x2] +
                 0.2 * image[:, x1 + w1: x2].astype(np.float32)).astype(self.background.dtype))

    def update(self, image: np.ndarray) -> None:
        """
        Обновляет фон.
        """
        self.mog2.apply(image, learningRate=0.4)
        self.background = self.mog2.getBackgroundImage()
