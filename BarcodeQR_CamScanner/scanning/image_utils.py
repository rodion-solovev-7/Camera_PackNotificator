"""
Универсальные функции, которые могут оказаться полезны при работе с изображениями.
"""
from functools import reduce

import cv2
import numpy as np


def get_resized(image: np.ndarray, *, sizer: float) -> np.ndarray:
    """
    Кратно изменяет размер изображения по ширине и высоте.
    """
    size = image.shape[:2][::-1]
    size = tuple(int(o * sizer) for o in size)
    resized = cv2.resize(image, size)
    return resized


def get_normalized_sum(image: np.ndarray) -> float:
    """
    Считает нормализованную [0.0; 1.0] сумму всех элементов многомерного массива.
    Где 1.0 означает, что все элементы имели максимальное значение,
    а 0.0 - все были нулями.
    """
    max_value = np.iinfo(image.dtype).max
    values_count = reduce(lambda x, y: x * y, image.shape)
    score = np.sum(image, dtype=np.uint64) * (1 / (max_value * values_count))
    return score
