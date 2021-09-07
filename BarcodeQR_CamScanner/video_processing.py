"""
Функции для работы с видеопотоком: чтение QR- и штрихкодов, распознавание наличия пачки
"""
from datetime import datetime
import multiprocessing as mp
from typing import Iterable

import cv2
import numpy as np

from .code_reading import get_codes_from_image, CodeType
from .events import *
from .pack_recognition.recognizers import BSPackRecognizer, NeuronetPackRecognizer
from .packs_image_logging import BaseImagesLogger, FakeImagesSaver


def _get_images_from_source(
        video_url: str,
        display_window: bool = True,
        auto_reconnect: bool = False,
) -> Iterable[np.ndarray]:
    """
    Генератор, возвращающий последовательность изображений из видео
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
        display_window: bool = True,
        auto_reconnect: bool = True,
        recognition_method: str = "BACKGROUND",
        recognizer_args=None,
        images_logger: BaseImagesLogger = FakeImagesSaver(),
) -> Iterable[CamScannerEvent]:
    """
    Генератор, возвращающий события с камеры-сканера
    """
    if recognizer_args is None:
        recognizer_args = {}
    if recognition_method == "BACKGROUND":
        pack_recognizer = BSPackRecognizer(**recognizer_args)
    elif recognition_method == "NEURONET":
        pack_recognizer = NeuronetPackRecognizer(**recognizer_args)
    else:
        yield TaskError(message=f"Некорректный способ распознавания: '{recognition_method}'")
        yield EndScanning()
        return

    # noinspection PyUnusedLocal
    is_pack_visible_before = False
    """Была ли ранее замечена пачка"""
    is_pack_visible_now = False
    """Замечена ли пачка сейчас"""

    last_correct_barcode = ''
    """Последний считанный штрихкод. 
    На случай, если с одной из пачек не считается её собственный"""

    pack = CameraPackResult()

    yield StartScanning(finish_time=datetime.now())

    images = _get_images_from_source(video_url, display_window, auto_reconnect)
    for image in images:
        is_pack_visible_before = is_pack_visible_now
        is_pack_visible_now = pack_recognizer.is_recognized(image)

        if is_pack_visible_now:
            # пачка проходит в данный момент

            if not is_pack_visible_before:
                # пачка впервые попала в кадр - создаём новую запись о пачке и фиксируем время
                pack = CameraPackResult()
                pack.start_time = datetime.now()

            # пытаемся прочитать QR и шрихкод
            image = _resize_image(image, sizer=0.4)
            images_logger.add(image)
            codes_dict = get_codes_from_image(image, sizer=1.0)

            # сохраняем коды, игнорируя повторы
            pack.qr_codes = list(dict.fromkeys(pack.qr_codes + codes_dict[CodeType.QR_CODE]))
            pack.barcodes = list(dict.fromkeys(pack.barcodes + codes_dict[CodeType.BARCODE]))
            continue

        if not is_pack_visible_now and is_pack_visible_before:
            # пачка только что прошла, подводим итоги

            # подгоняем кол-во штрихкодов к кол-ву QR-кодов:
            # если не смогли считать штрихкод, то берём предыдущий считанный
            if len(pack.barcodes) > 0:
                last_correct_barcode = pack.barcodes[-1]
            missing_barcodes_count = max(0, len(pack.qr_codes) - len(pack.barcodes))
            pack.barcodes.extend([last_correct_barcode] * missing_barcodes_count)

            if len(pack.qr_codes) == 0:
                images_logger.save()
            images_logger.clear()

            pack.finish_time = datetime.now()
            yield pack
            continue

    yield EndScanning(finish_time=datetime.now())


class CameraScannerProcess(mp.Process):
    """
    Процесс - источник событий с камеры.
    Общается с управляющим процессом через ``queue``.
    """

    def __init__(self, *args):
        super().__init__(
            target=self.task,
            args=tuple(args),
            daemon=True
        )

    @staticmethod
    def task(
            queue: mp.Queue,
            worker_id: int,
            video_url: str,
            display_window: bool,
            auto_reconnect: bool,
            recognition_method: str,
            recognizer_args: dict,
            images_logger: BaseImagesLogger,
    ) -> None:
        """
        Метод для запуска в отдельном процессе.

        Бесконечное читает QR-, штрихкоды с выбранной камеры
        и отправляет их данные базовому процессу через ``queue``.

        Кладёт в ``queue`` следующие события-наследники от ``CamScannerEvent``:

        - В случае ошибок экземпляр ``TaskError`` с информацией об ошибке.
        - В случае успешной обработки экземпляр ``CameraPackResult`` со считанными данными.
        """
        try:
            events = get_events_from_video(
                video_url=video_url,
                display_window=display_window,
                auto_reconnect=auto_reconnect,
                recognition_method=recognition_method,
                recognizer_args=recognizer_args,
                images_logger=images_logger,
            )

            # бесконечный цикл, который получает события от камеры и кладёт их в очередь
            for event in events:
                event.worker_id = worker_id
                event.receive_time = None

                # отправка события основному процессу
                queue.put(event)
        except KeyboardInterrupt:
            pass
