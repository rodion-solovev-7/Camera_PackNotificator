"""
Методы для определения объектов и событий с изображения.
"""
from functools import reduce

import numpy as np
import cv2
from scipy.ndimage import gaussian_filter1d


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


def get_absdiff_motion_score(
        img1: np.ndarray,
        img2: np.ndarray,
) -> float:
    """
    Вычисление показателя движения (от 0.0 до 1.0) между 3-мя изображениями.

    Для корректного результата изображения должны идти в хронологическом порядке.
    """
    diff_mask = cv2.absdiff(img1, img2)
    cv2.threshold(diff_mask, 5, 1, cv2.THRESH_BINARY, dst=diff_mask)
    score = get_normalized_sum(diff_mask)
    return score


def get_mog2_foreground_score(
        image: np.ndarray,
        mog2: cv2.BackgroundSubtractorMOG2,
        *,
        learning_rate: float = 0.001,
) -> float:
    """
    Вычисление показателя различности изображения с фоном.
    """
    mask = mog2.apply(image, learningRate=learning_rate)
    score = get_normalized_sum(mask)
    return score


def is_object_spawning_mog2(
        spawn: np.ndarray,
        mog2: cv2.BackgroundSubtractorMOG2,
        *,
        learning_rate: float = 0.0,
        threshold_score: float = 0.8,
) -> bool:
    """
    Определяет, появляется ли новый объект в данный момент, через mog2 foreground.
    """
    score = get_mog2_foreground_score(spawn, mog2, learning_rate=learning_rate)
    return score >= threshold_score


def is_pack_object_spawning_absdiff(
        spawn: np.ndarray,
        spawn_old: np.ndarray,
        *,
        threshold_score: float = 0.8,
) -> bool:
    """
    Определяет, появляется ли новый объект в данный момент, через absdiff.
    """
    score = get_absdiff_motion_score(spawn, spawn_old)
    return score >= threshold_score


def get_object_bounds_mog2(
        image: np.ndarray,
        mog2: cv2.BackgroundSubtractorMOG2,
        *,
        pack_width_in_px: int = 143,
        threshold_score: float = 0.40,
        threshold_activation_score: float = 0.55,
) -> list[tuple[int, int, int, int]]:
    """
    Определяет позиции объектов через BackgroundSubstraction.

    Возвращает список с bounding_box'ами.

    Example:
        >>> get_object_bounds_mog2(image)
        [(10, 0, 50, 30), (80, 0, 32, 30), (203, 0, 45, 30)]

        Здесь в диапазоне координат X=[10;60] Y=[0;30] обнаружена пачка
        (аналогично с X=[80;112] Y=[0;30] и X=[203; 248] Y=[0;30])
    """
    mask = mog2.apply(image, learningRate=0)

    erode_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    dilate_kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (7, 7))
    cv2.erode(mask, erode_kernel, dst=mask, iterations=2)
    cv2.dilate(mask, dilate_kernel, dst=mask, iterations=1)

    linesum = mask.sum(axis=0)

    # сглаживание
    smooth_kernel_size = pack_width_in_px // 12
    smoothed = gaussian_filter1d(linesum, smooth_kernel_size, output=linesum)
    smoothed = smoothed.astype(np.float32) * (1 / (0xff * mask.shape[0]))

    # определение пачек через сумму маски для каждого X
    flags = (smoothed >= threshold_score).astype(np.int8)
    pack_borders = flags[1:] - flags[:-1]

    beg_borders = np.where(pack_borders == +1)[0]
    end_borders = np.where(pack_borders == -1)[0]

    if len(beg_borders) > 0 and len(end_borders) > 0:
        if beg_borders[0] > end_borders[0]:
            beg_borders = np.insert(beg_borders, 0, 0, axis=0)
        if beg_borders[-1] > end_borders[-1]:
            end_borders = np.insert(end_borders, -1, 0, axis=0)

    w, h = image.shape[:2][::-1]
    pack_ranges = [(b, 0, e - b, h)
                   for b, e in zip(beg_borders, end_borders)
                   if np.any(smoothed[b:e] >= threshold_activation_score)]

    return pack_ranges
