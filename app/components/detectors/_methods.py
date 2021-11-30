"""
Методы для определения объектов и событий с изображения.
"""
from functools import reduce

import cv2
import numpy as np
from tensorflow.lite.python.interpreter import Interpreter


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


def get_neuronet_score(interpreter: Interpreter, image: np.ndarray) -> float:
    """
    Оценка наличия пачки на изображении, полученная от нейросети

    **Осторожно: очень долго (200мс/кадр) работает!**

    Args:
        interpreter: интерпретатор с уже загруженной и обученной нейросетью
        image: изображение, которое нужно проверить

    Returns:
        показатель движения на изображении
            0.0 (движения нет) до 1.0 (на изображении двигаются все пиксели)
    """
    input_detail: dict = interpreter.get_input_details()[0]
    output_detail: dict = interpreter.get_output_details()[0]

    input_size = tuple(input_detail['shape'][[2, 1]])

    image = cv2.resize(image, input_size)
    cv2.cvtColor(image, cv2.COLOR_BGR2RGB, image)

    input_layer = np.expand_dims(image, axis=0)
    input_layer = input_layer.astype(np.float32) * (1 / 255)

    interpreter.set_tensor(input_detail['index'], input_layer)
    interpreter.invoke()

    predict_value = interpreter.get_tensor(output_detail['index'])[0][0]
    return predict_value


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
