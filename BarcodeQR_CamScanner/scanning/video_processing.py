"""
Функции для работы с видеопотоком: чтение QR- и штрихкодов, распознавание наличия пачки
"""
from datetime import datetime
from typing import Iterable

import cv2
import numpy as np

from .code_reading import get_codes_from_image, CodeType
from .image_loggers import BaseImagesLogger
from .pack_recognition.recognizers import BaseRecognizer
from ..models import CameraPackResult, CameraProcessEvent


def _get_images_from_source(
        video_url: str,
        *,
        display_window: bool,
        auto_reconnect: bool,
) -> Iterable[np.ndarray]:
    """
    Генератор, возвращающий последовательность изображений из видео.
    Если ``auto_reconnect=True``
    """
    cap = cv2.VideoCapture(video_url)
    while True:
        is_exists, image = cap.read()
        if not is_exists:
            if not auto_reconnect:
                break

            # переподключение
            cap.release()
            cap.open(video_url)
            continue

        if display_window:
            img2display = _resize_image(image, 0.25)
            cv2.imshow('', img2display)
            cv2.waitKey(1)

        yield image
    cap.release()
    cv2.destroyAllWindows()


def _resize_image(image: np.ndarray, sizer: float) -> np.ndarray:
    """Меняет размер изображения не изменяя соотношения"""
    shape = tuple(int(v * sizer) for v in image.shape[:2])
    return cv2.resize(image, shape[::-1])


def get_events_from_video(
        video_url: str,
        recognizer: BaseRecognizer,
        images_logger: BaseImagesLogger,
        display_window: bool = True,
        auto_reconnect: bool = True,
) -> Iterable[CameraProcessEvent]:
    """
    Генератор, возвращающий события с камеры-сканера
    """
    # noinspection PyUnusedLocal
    is_pack_visible_before = False
    """Была ли ранее замечена пачка"""
    is_pack_visible_now = False
    """Замечена ли пачка сейчас"""

    last_correct_barcode = ''
    """Последний считанный штрихкод. 
    На случай, если с одной из пачек не считается её собственный"""

    pack = CameraPackResult(start_time=datetime.now())

    images = _get_images_from_source(
        video_url,
        display_window=display_window,
        auto_reconnect=auto_reconnect,
    )

    qr_codes = []
    barcodes = []
    for image in images:
        is_pack_visible_before = is_pack_visible_now
        is_pack_visible_now = recognizer.is_recognized(image)

        if is_pack_visible_now:
            # пачка проходит в данный момент

            if not is_pack_visible_before:
                # пачка впервые попала в кадр - создаём новую запись о пачке и фиксируем время
                pack = CameraPackResult(start_time=datetime.now())

            # пытаемся прочитать QR и шрихкод
            image = _resize_image(image, sizer=0.5)
            images_logger.add(image)

            codes_dict = get_codes_from_image(image)
            new_qr_codes = codes_dict[CodeType.QR_CODE]
            new_barcodes = codes_dict[CodeType.BARCODE]

            # сохраняем коды, игнорируя повторы
            # ключи словарей не допускают повторов и хранятся в порядке добавления
            if len(new_qr_codes) > 0:
                qr_codes += [code for code in new_qr_codes if code not in qr_codes]
            if len(new_barcodes) > 0 and len(barcodes) <= len(qr_codes):
                barcodes += [code for code in new_barcodes if code not in barcodes]
            continue

        if not is_pack_visible_now and is_pack_visible_before:
            # пачка только что прошла, подводим итоги

            # подгоняем кол-во штрихкодов к кол-ву QR-кодов:
            # если не смогли считать штрихкод, то берём предыдущий считанный
            if len(barcodes) > 0:
                last_correct_barcode = barcodes[-1]

            while len(barcodes) > len(qr_codes):
                barcodes.pop()
            while len(barcodes) < len(qr_codes):
                barcodes.append(last_correct_barcode)

            # если с группы пачек не считано ни одного QR-кода, то сохраняем изображения этой группы
            if len(qr_codes) == 0:
                images_logger.save()
            images_logger.clear()

            pack.codepairs = [{
                CodeType.QR_CODE: qr_code,
                CodeType.BARCODE: barcode,
            } for qr_code, barcode in zip(qr_codes, barcodes)]
            pack.finish_time = datetime.now()
            yield pack

            qr_codes.clear()
            barcodes.clear()
            continue
