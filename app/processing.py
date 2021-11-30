"""
Главный метод обработки видео.
"""
import asyncio
import copy
from collections import deque
from multiprocessing.pool import ThreadPool as Pool

import cv2
import numpy as np
from loguru import logger

from .components.accessors import BaseAccessor
from .components.detectors import BaseDetector
from .components.notifiers import BaseNotifier
from .components.validators import BaseValidator

from .image_utils import get_codes_from_image, get_sliced_image


def assert_video_is_ok(video_path: str) -> None:
    """
    Проверяет, что видео доступно и читается.
    Если нет - выкидывает AssertionError.
    """
    cap = cv2.VideoCapture()
    cap.open(video_path)
    assert cap.isOpened(), "Видеопоток не открыт!"
    is_exists, _ = cap.read()
    assert is_exists, "Не удалось получить кадр видеопотока!"
    cap.release()


class FakeApplyResult:
    """
    Заглушка для будущей многопоточной обработки
    """

    def __init__(self, data):
        self.data = data

    @staticmethod
    def ready():
        """
        Говорит о готовности 'многопоточной' задачи
        """
        return True

    def get(self):
        """
        Возвращает результаты обработки
        """
        return self.data


def process_frame(frame: np.ndarray, *, sizer: float = 1.0) -> np.ndarray:
    """
    Обрабатывает кадр. Возвращает необходимые данные
    (позиции, bounding box'ы, предобработанные изображения)
    в виде кортежа или словаря.
    """
    return cv2.resize(frame, None, fx=sizer, fy=sizer)


def get_codes_image_region(full_image: np.ndarray) -> np.ndarray:
    """
    Получает с изображения фрагмент, где обычно находятся коды.
    """
    conveyor = get_sliced_image(
        full_image,
        h_slice=(0.00, 1.00),
        w_slice=(0.00, 1.00),
    )
    return conveyor


def process_video(
        video_path: str,
        detector: BaseDetector,
        notifier: BaseNotifier,
        accessor: BaseAccessor,
        validator: BaseValidator,
        eventloop: asyncio.AbstractEventLoop,
        *,
        capture_buffer_size: int = 6,
        threads_count: int = None,
        video_sizer: float = 1.0,
        show_video: bool = True,
        interact_on_input: bool = True,
) -> None:
    """
    Обработка видео. Главный метод программы.

    Args:
        video_path: путь к видео с камеры
        detector: объект, который определяет, присутствуют ли пачки на изображении
        notifier: обёртка для сетевого оповещения о корректности пачек
        accessor: обёртка для получения актуальных данных от бэкенда
        validator: класс с логикой, отвечающей за валидацию собранных данных
        eventloop: асинхронный событийный цикл,
                   должен быть уже запущен и работать параллельно
        capture_buffer_size: кол-во кадров, хранящихся в буффере видеопотоков
        video_sizer: коэффициент уменьшения кадров с видео
        show_video: отображать видео на экране
        threads_count: кол-во потоков, используемых для одновременной обработки видео
        interact_on_input: прекращать обработку при нажатии esc или q,
                           а также ставить на паузу при нажатии пробела
                           (игнорируется при show_video=False)
    """

    if threads_count is None:
        threads_count = cv2.getNumberOfCPUs() // 2 + 1

    assert_video_is_ok(video_path)
    assert 0 < video_sizer <= 1.0, "Коэффициент размера изображения должен быть (0.0; 1.0]"
    assert 0 < threads_count, "Кол-во потоков должно быть целым положительным числом"

    cap = cv2.VideoCapture(video_path)
    pool = Pool(processes=threads_count)
    pending = deque()

    # клавиши для выхода
    stop_keys = [27, ord('q'), ord('Q'), ]

    # уменьшение размера буффера
    # (если обработка видео будет запаздывать,
    # то большой буффер будет приводить к задержкам)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, capture_buffer_size)

    last_barcode = '0' * 13

    # noinspection PyUnusedLocal
    is_prev_pack_exists = False
    is_curr_pack_exists = False

    empty_record = {
        'QRCODE': [],
        'EAN13': [],
    }
    record = copy.deepcopy(empty_record)

    while True:
        if len(pending) < threads_count:
            exists, frame = cap.read()

            if not exists:
                logger.error("Видеопоток: кадр не был получен. Переподключение")
                cap.open(video_path)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, capture_buffer_size)
                continue

            pack_img = get_codes_image_region(frame)

            task = FakeApplyResult(process_frame(pack_img, sizer=video_sizer))

            # TODO: продумать синхронизацию данных при многопоточном подходе
            # task = pool.apply_async(
            #     process_frame,
            #     args=(pack_img.copy(),),
            #     kwds=dict(sizer=video_sizer),
            # )

            pending.append(task)

        while len(pending) > 0 and pending[0].ready():
            pack_img = pending.popleft().get()

            # определение наличия пачки
            is_prev_pack_exists = is_curr_pack_exists
            is_curr_pack_exists = detector.is_detected(pack_img)

            if is_curr_pack_exists:
                if not is_prev_pack_exists:
                    record = copy.deepcopy(empty_record)

                codes = get_codes_from_image(pack_img)
                record['QRCODE'] = list(dict.fromkeys(record['QRCODE'] + codes['QRCODE']))
                record['EAN13'] = list(dict.fromkeys(record['EAN13'] + codes['EAN13']))

            elif is_prev_pack_exists:

                if len(record['EAN13']) > 0:
                    last_barcode = record['EAN13'][-1]

                # генерация недостающих штрих-кодов
                while len(record['EAN13']) < len(record['QRCODE']):
                    record['EAN13'].append(last_barcode)
                while len(record['EAN13']) > len(record['QRCODE']):
                    record['EAN13'].pop()

                record['expected'] = accessor.get_expected_codes_count()
                validated = validator.get_validated(record)

                if validated['is_valid']:
                    notify = notifier.notify_about_good_pack
                else:
                    notify = notifier.notify_about_bad_pack
                asyncio.run_coroutine_threadsafe(notify(validated), eventloop)

                record = copy.deepcopy(empty_record)

            if show_video:
                cv2.imshow('conveyor', pack_img)

                key = cv2.waitKey(1)
                if interact_on_input:
                    if key in stop_keys:
                        # завершение обработки при нажатии esc или q
                        raise KeyboardInterrupt()

                    if key == ord(' '):
                        # пауза
                        cv2.waitKey(0)
