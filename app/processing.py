"""
Главный метод обработки видео.
"""
import asyncio
from collections import deque
from multiprocessing.pool import ThreadPool

import cv2
import numpy as np
from loguru import logger

from .network.senders import BaseApi
from .video.detectors import BasePackDetector
from .video.regions_extraction import get_conveyor_image
from .video.trackers import BasePackTracker
from .video.utils import draw_text


def process_frame(frame: np.ndarray) -> np.ndarray:
    """
    Обрабатывает кадр. Возвращает необходимые данные
    (позиции, bounding box'ы, предобработанные изображения)
    в виде кортежа или словаря.
    """
    return frame


def process_video(
        video_path: str,
        detector: BasePackDetector,
        tracker: BasePackTracker,
        eventloop: asyncio.AbstractEventLoop,
        api: BaseApi,
        *,
        capture_buffer_size: int = 3,
        video_sizer: float = 1.0,
        show_video: bool = True,
        interact_on_input: bool = True,
) -> None:
    """
    Обработка видео. Главный метод программы.

    Args:
        video_path: путь к видео с камеры
        detector: объект, который находит положение пачек на изображении
        tracker: объект, который мониторит положение пачек
                      и хранит привязанные к ним данные
        api: обёртка для сетевого взаимодействия
        eventloop: асинхронный событийный цикл,
                   должен быть уже запущен и работать параллельно
        capture_buffer_size: кол-во кадров, хранящихся в буффере видеопотоков
        video_sizer: коэффициент уменьшения кадров с видео
        show_video: отображать видео на экране
        interact_on_input: прекращать обработку при нажатии esc или q,
                           а также ставить на паузу при нажатии пробела
                           (игнорируется при show_video=False)

    Returns:
        None
    """
    stop_keys = [27, ord('q'), ord('Q')]

    cap = cv2.VideoCapture(video_path)

    # уменьшение размера буффера
    # (в случае если обработка видео будет запаздывать,
    # то большой буффер будет приводить к задержкам)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, capture_buffer_size)

    assert cap.isOpened(), "Видеопоток не открыт!"
    assert 0 < video_sizer <= 1.0, "Коэффициент размера изображения должен быть (0.0; 1.0]"

    thread_count = cv2.getNumberOfCPUs() // 2 + 1
    pool = ThreadPool(processes=thread_count)
    pending = deque()

    while True:
        if len(pending) < thread_count:
            exists, frame = cap.read()

            if not exists:
                logger.error("Видеопоток: кадр не был получен. Переподключение")
                cap.open(video_path)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, capture_buffer_size)
                continue

            conveyor = get_conveyor_image(frame)
            task = pool.apply_async(process_frame, (conveyor.copy(),))

            pending.append(task)

        while len(pending) > 0 and pending[0].ready():
            conveyor = pending.popleft().get()

            # трекинг объектов вдоль основного конвейера
            pack_boxes = detector.get_object_boxes(conveyor)
            tracking_results = tracker.update(pack_boxes)

            if len(tracking_results) > 0:
                asyncio.run_coroutine_threadsafe(api.notify_object_spawned(track_id=0), eventloop)
                asyncio.run_coroutine_threadsafe(api.notify_object_delivered(track_id=1), eventloop)
                asyncio.run_coroutine_threadsafe(api.notify_object_confiscated(track_id=2), eventloop)

            if show_video:
                cv2.imshow('conveyor', conveyor)

                key = cv2.waitKey(1)
                if interact_on_input:
                    if key in stop_keys:
                        # завершение обработки при нажатии esc или q
                        raise KeyboardInterrupt()

                    if key == ord(' '):
                        # пауза
                        cv2.waitKey(0)


def display_elapsed(
        image: np.ndarray,
        seconds: float,
        text_pos: tuple[int, int] = (15, 30),
) -> None:
    """
    Отображает затраченное на обработку кадра время.
    """
    milliseconds = seconds * 1000
    text = f"elapsed = {milliseconds:.1f} ms"

    draw_text(image, text_pos, text, color=(0, 0, 0x00), font_scale=1.0, thickness=2)
    draw_text(image, text_pos, text, color=(0, 0, 0xff), font_scale=1.0, thickness=1)
