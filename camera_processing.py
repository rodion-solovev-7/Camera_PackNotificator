from datetime import datetime
from typing import Iterable, Dict, List, Any, Tuple, Optional

import cv2
import numpy as np
from cv2 import VideoCapture, resize, cvtColor, COLOR_BGR2RGB, CAP_PROP_FRAME_WIDTH, CAP_PROP_FRAME_HEIGHT, imshow
from numpy import ndarray
from tensorflow.lite.python.interpreter import Interpreter

from recognition import ORIG_X, ORIG_Y, dummy_codes
from worker_events import TaskResult, CamScannerEvent, TaskError


def check_pack_on_image(interpreter: Interpreter, image: ndarray) -> bool:
    """Проверяет наличие pack'а на изображении."""

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
        images: List[ndarray],
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


def event_iterator(
        video_url: str,
        model_path: str,
) -> Iterable[CamScannerEvent]:
    """
    Бесконечный итератор, возвращающий события с камеры-сканера.
    """

    video: VideoCapture = VideoCapture(video_url)
    width: float = video.get(CAP_PROP_FRAME_WIDTH)
    height: float = video.get(CAP_PROP_FRAME_HEIGHT)

    interpreter: Interpreter = Interpreter(model_path=model_path)
    interpreter.allocate_tensors()

    MAX_IMAGES_COUNT = 150
    FRAMES_PER_CHECK = 15
    last_images = []

    last_barcode = None
    result_barcode = None
    result_qr_code = None

    is_result_complete = False
    is_pack_visible = False
    is_pack_previously_visible = False

    i = 0
    while True:
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

        is_image_exists, image = video.read()
        is_image_exists: bool
        image: ndarray

        if not is_image_exists:
            message = "Нет изображения! Попытка переподключения к источнику"
            yield TaskError(
                error_message=message,
                finish_time=datetime.now(),
            )
            video.release()
            video = VideoCapture(video_url)
            continue

        image2 = resize(image, (ORIG_X, ORIG_Y))
        imshow('image', image2)

        # TODO: возможно стоит или убрать буффер с картинками (возможная потеря функционала ?),
        #  или начать его использовать (потеря производительности ?)
        last_images.append(image2)
        if len(last_images) > MAX_IMAGES_COUNT:
            last_images.pop(0)

        i = (i + 1) % FRAMES_PER_CHECK
        if i == 0:
            is_pack_visible = check_pack_on_image(interpreter, image)

        if not is_pack_visible and not is_pack_previously_visible:
            continue

        if is_pack_visible:
            is_pack_previously_visible = True
            if is_result_complete:
                continue

            # TODO: возможно, здесь предполагалось использовать буффер с изображениями,
            #  а не одну картинку (в таком случае, у image и image2 не совпадают размеры)
            images = [image]

            barcode, qr_code = read_barcode_and_qr(images, width, height)

            result_qr_code = qr_code if result_qr_code is None else result_qr_code
            result_barcode = barcode if result_barcode is None else result_barcode

            is_result_complete = result_qr_code is not None and result_barcode is not None
            continue

        if not is_pack_visible and is_pack_previously_visible:
            # пачка только что прошла, подводим итоги

            if result_barcode is None:
                result_barcode = last_barcode
            last_barcode = result_barcode

            yield TaskResult(
                qr_code=result_qr_code,
                barcode=result_barcode,
                finish_time=datetime.now(),
            )

            last_images.clear()
            is_pack_previously_visible = False
            is_result_complete = False
            result_qr_code = None
            result_barcode = None
            continue
