from collections import deque
from datetime import datetime
from typing import Iterable, Dict, List, Any, Tuple, Optional

import numpy as np
from cv2 import (VideoCapture, resize, cvtColor, COLOR_BGR2RGB, CAP_PROP_FRAME_WIDTH,
                 CAP_PROP_FRAME_HEIGHT, imshow, waitKey)
from numpy import ndarray
from tensorflow.lite.python.interpreter import Interpreter

from recognition import ORIG_X, ORIG_Y, dummy_codes
from worker_events import TaskResult, CamScannerEvent, TaskError, EndScanning


def is_pack_exists(interpreter: Interpreter, image: ndarray) -> bool:
    """Проверяет наличие пачки на изображении."""

    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()
    input_details: List[Dict[str, Any]]
    output_details: List[Dict[str, Any]]

    # TODO: размер (248 x 136) не фигурирует больше нигде в коде.
    #  Возможно, стоит его поменять/вынести в константу
    rgb_image = resize(image, (248, 136))
    rgb_image = cvtColor(rgb_image, COLOR_BGR2RGB)
    rgb_image = np.expand_dims(rgb_image, axis=0)

    try:
        img = rgb_image.astype('float32') / 255
        interpreter.set_tensor(input_details[0]['index'], img)
        interpreter.invoke()

        predict_value = interpreter.get_tensor(output_details[0]['index'])[0][0]
        return predict_value > 0.5

    # TODO: проверить наличие и конкретизировать исключение, либо убрать проверку
    except Exception:
        return False


def read_barcode_and_qr(
        images: Iterable[ndarray],
        width: float,
        height: float,
) -> Tuple[Optional[str], Optional[str]]:
    """Читает QR- и штрихкод с изображения."""
    try:
        barcode, qr_code = dummy_codes(images, width, height, 0.4)
        barcode = barcode if barcode != '' else None
        qr_code = qr_code if qr_code != '' else None
        return barcode, qr_code

    # TODO: проверить наличие и конкретизировать исключение, либо убрать проверку
    except Exception:
        return None, None


def display_image(image: ndarray) -> None:
    """
    Рендерит текущий кадр из видео.

    (Плохо влияет на производительность, но позволяет
    в реальном времени следить за ситуацией.)
    """
    image2display = resize(image, (ORIG_X, ORIG_Y))
    imshow('image', image2display)
    waitKey(1)


def reconnect_to_video_if_need(
        video_url: str,
        video: Optional[VideoCapture] = None,
) -> VideoCapture:
    """
    Проверяет доступность видео и переподключается к источнику, если необходимо.
    """
    if video is not None:
        video.release()
    return VideoCapture(video_url)


def get_events(
        video_url: str,
        model_path: str,
        display: bool = True,
        auto_reconnect: bool = True,
) -> Iterable[CamScannerEvent]:
    """
    Бесконечный итератор, возвращающий события с камеры-сканера.
    """

    video: VideoCapture = reconnect_to_video_if_need(video_url)
    width: float = video.get(CAP_PROP_FRAME_WIDTH)
    height: float = video.get(CAP_PROP_FRAME_HEIGHT)

    interpreter: Interpreter = Interpreter(model_path=model_path)
    interpreter.allocate_tensors()

    # больше значений - больше подвисаний
    MAX_IMAGES_COUNT = 1
    FRAMES_PER_CHECK = 15
    last_images = deque()

    last_barcode = None
    result_barcode = None
    result_qr_code = None

    is_result_complete = False
    is_pack_visible_now = False
    is_pack_visible_before = False

    frame_counter = 0
    while True:
        is_image_exists, image = video.read()
        is_image_exists: bool
        image: ndarray

        if not is_image_exists:
            message = "Нет изображения!"
            yield TaskError(
                message=message,
                finish_time=datetime.now(),
            )

            if not auto_reconnect:
                break

            # TODO: возможно стоит сообщать что-то вроде
            #  "Нет изображения! Попытка переподключения к источнику"
            video = reconnect_to_video_if_need(video_url, video)
            continue

        if display:
            display_image(image)

        last_images.append(image)
        while len(last_images) > MAX_IMAGES_COUNT:
            last_images.popleft()

        frame_counter = (frame_counter + 1) % FRAMES_PER_CHECK
        if frame_counter == 0:
            is_pack_visible_now = is_pack_exists(interpreter, image)

        if not is_pack_visible_now and not is_pack_visible_before:
            continue

        if is_pack_visible_now:
            is_pack_visible_before = True

            if is_result_complete:
                continue

            barcode, qr_code = read_barcode_and_qr(last_images, width, height)

            result_qr_code = qr_code if result_qr_code is None else result_qr_code
            result_barcode = barcode if result_barcode is None else result_barcode

            is_result_complete = result_qr_code is not None and result_barcode is not None
            continue

        if not is_pack_visible_now and is_pack_visible_before:
            # пачка только что прошла, подводим итоги

            # если не смогли считать текущий штрихкод, отправляем предыдущий считанный
            result_barcode = last_barcode if result_barcode is None else result_barcode
            last_barcode = result_barcode

            yield TaskResult(
                qr_code=result_qr_code,
                barcode=result_barcode,
                finish_time=datetime.now(),
            )

            last_images.clear()
            is_pack_visible_before = False
            is_result_complete = False
            result_qr_code = None
            result_barcode = None
            continue

    message = "Завершение работы"
    yield EndScanning(
        message=message,
        finish_time=datetime.now(),
    )
    video.release()
