"""
Набор функций для предобработки изображений, склейки и извлечения из них необходимых зон.
"""
import numpy as np

from .utils import get_sliced_image


def get_conveyor_image(full_image: np.ndarray) -> np.ndarray:
    """
    Получает с изображения фрагмент с конвейером.
    """
    conveyor = get_sliced_image(
        full_image,
        h_slice=(0.15, 0.60),
        w_slice=(0.00, 0.90),
    )
    return conveyor


def get_1st_spawn_image(full_image: np.ndarray) -> np.ndarray:
    """
    Получает с изображения фрагмент с 1-ым конвейером-источником.
    """
    spawn = get_sliced_image(
        full_image,
        h_slice=(0.50, 1.000),
        w_slice=(0.00, 0.125),
    )
    return spawn


def get_2nd_spawn_image(full_image: np.ndarray) -> np.ndarray:
    """
    Получает с изображения фрагмент с 2-ым конвейером-источником.
    """
    spawn = get_sliced_image(
        full_image,
        h_slice=(0.50, 1.000),
        w_slice=(0.28, 0.405),
    )
    return spawn


def get_confiscation_zone_image(full_image: np.ndarray) -> np.ndarray:
    """
    Получает с изображения фрагмент с зоной изъятия.
    """
    confiscation = get_sliced_image(
        full_image,
        h_slice=(0.10, 0.65),
        w_slice=(0.46, 0.69),
    )
    return confiscation
