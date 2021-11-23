"""
Универсальные функции для обработки изображений или других np-массивов, которые облегчают жизнь.
Делают простые действия и не зависят от конкретного проекта.
"""

import cv2
import numpy as np

__all__ = [
    'get_sliced_image',
    'sharpen_image',
    'draw_text',
    'draw_circle',
]


def get_sliced_image(
    image: np.ndarray,
    *,
    w_slice: tuple[float, float] = (0.0, 1.0),
    h_slice: tuple[float, float] = (0.0, 1.0),
) -> np.ndarray:
    """
    Возвращает фрагмент исходного изображения (без копирования).
    Срез задаётся числами с плавающей точкой - [0.0; 1.0].
    """
    w, h = image.shape[:2][::-1]

    w_slice = int(w * w_slice[0]), int(w * w_slice[1])
    h_slice = int(h * h_slice[0]), int(h * h_slice[1])

    # no copy
    return image[h_slice[0]:h_slice[1], w_slice[0]:w_slice[1]]


def sharpen_image(image: np.ndarray) -> None:
    """
    Делает контуры изображения более резкими (без копирования).
    """
    sharpen_kernel = np.array([
        [-1, -1, -1],
        [-1, +9, -1],
        [-1, -1, -1],
    ])
    cv2.filter2D(image, -1, sharpen_kernel, image)


def draw_text(
    frame: np.ndarray,
    point: tuple[int, int],
    text: str,
    *,
    color: tuple[int, int, int] = (0, 0, 255),
    font_scale: float = 1.0,
    thickness: int = 1,
    font: int = cv2.FONT_HERSHEY_COMPLEX_SMALL,
) -> None:
    """
    Добавляет на изображение текст в выбранной позиции (без копирования).
    """
    cv2.putText(frame, text, point, font, font_scale, color, thickness, cv2.LINE_AA)


def draw_circle(
        frame: np.ndarray,
        point: tuple[int, int],
        radius: int,
        *,
        color: tuple[int, int, int] = (0, 0, 255),
        thickness: float = 1.0,
):
    """
    Добавляет на изображение круг (без копирования).
    """
    cv2.circle(frame, point, radius, color, thickness)


def get_undistorded_fisheye(
        frame: np.ndarray,
        k1: float,
        k2: float,
        p1: float,
        p2: float,
        *,
        sizer: float = 1.0,
        focal_x: float = 1000,
        focal_y: float = 1000,
):
    """
    Исправление дефекта рыбьего глаза

    Params:
        frame: входное изображение

    Return:
        result: исправленное изображение
    """
    if sizer != 1.0:
        frame = cv2.resize(frame, None, fx=sizer, fy=sizer)

    h, w = frame.shape[:2]

    # заполняем матрицу преобразования 3x3
    cam = np.identity(3, dtype=np.float64)

    # фокусное расстояние с учётом предварительного изменения размера
    cam[0, 0] = focal_x * sizer
    cam[1, 1] = focal_y * sizer
    cam[2, 2] = 1.0

    # центр
    cam[0, 2] = w / 2
    cam[1, 2] = h / 2

    coeff = np.array(
        [k1, k2, p1, p2],
        dtype=np.float64
    ).reshape((4, 1))

    return cv2.undistort(frame, cam, coeff, None, None)
