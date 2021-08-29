import os
from datetime import datetime, timedelta
from multiprocessing import Queue, Process
from queue import Empty
from typing import Iterable, Optional

from loguru import logger

from .communication.signals import (get_pack_codes_count, notify_about_packdata,
                                    send_shutter_down, send_shutter_up)
from .events import *
from .events.handling import EventProcessor, EventsProcessingQueue
from .packs_processing import InstantCameraProcessingQueue
from .video_processing import CameraScannerProcess


class RunnerWith1Camera:
    def __init__(self, camera_args: tuple, domain_url: str):
        self._queue = Queue()
        self._event_processor = EventProcessor()
        self._cam_validating_queue = InstantCameraProcessingQueue()
        self._domain_url = domain_url
        self._expected_codes_count = 2
        self._camera_args = camera_args
        self._processes = self._get_processes([camera_args])

        self._init_event_processor()

        self._event_processing_queue = EventsProcessingQueue(self._event_processor)

    def _get_processes(self, processes_args) -> list[Process]:
        """Инициализирует и возвращает процессы"""
        processes = [CameraScannerProcess(self._queue, worker_id, *args)
                     for worker_id, args in enumerate(processes_args)]
        return processes

    def _run_processes(self) -> None:
        """Запускает процессы"""
        for process in self._processes:
            process.start()

    def _kill_processes(self) -> None:
        """Убивает процессы"""
        for process in self._processes:
            if not process.is_alive():
                continue
            process.terminate()
            process.join()

    def _init_event_processor(self):
        handlers = [
            self._process_camerapackresult,
            self._process_taskerror,
            self._process_startscanning,
            self._process_endscanning,
            self._process_packbadcodes,
            self._process_packwithcodes,
        ]
        for handler in handlers:
            self._event_processor.add_handler(handler)

    def _get_event_from_cam(self) -> Optional[CamScannerEvent]:
        QUEUE_REQUEST_TIMEOUT_SEC = 1.5
        try:
            event = self._queue.get(timeout=QUEUE_REQUEST_TIMEOUT_SEC)
            return event
        except Empty:
            return None

    def mainloop_with_lock(self) -> None:
        """
        Запускает обработку QR- и штрихкодов с камеры,
        открывает блокирующий событийный цикл для обработки приходящих от неё событий.

        Отлавливает и логгирует доходящие до него некритичные исключения.

        Завершается при ``KeyboardInterrupt`` (Ctrl+C в терминале)
        """

        # TODO: инициализировать стартовые события здесь

        while True:
            try:
                # тут происходит обработка событий из списка с событиями
                # - вызывается подходящий метод self._process_*Событие*
                # и создаются новые события
                self._event_processing_queue.process_latest()

            except Exception as e:
                logger.exception("Неотловленное исключение")
                logger.opt(exception=e)

    def _update_expected_codes_count(self) -> None:
        new_codes_count = get_pack_codes_count(self._domain_url)
        if new_codes_count is not None:
            self.expected_codes_count = new_codes_count

    def _process_camerapackresult(self, event: CameraPackResult) -> None:
        msg = (f"Получены данные от камеры: "
               f"QR={event.qr_codes} "
               f"BAR={event.barcodes} "
               f"время пачки='{event.start_time} - {event.finish_time}'")
        logger.debug(msg)
        event.receive_time = datetime.now()
        event.expected_codes_count = self._expected_codes_count
        self._cam_validating_queue.enqueue(event)
        yield from self._cam_validating_queue.get_processed_latest()

    def _process_update_expected_codes_count(
            self,
            event: UpdateExpectedCodesCount,
    ) -> Iterable[UpdateExpectedCodesCount]:
        now = datetime.now()
        if now >= event.update_time:
            self._update_expected_codes_count()
            update_time = datetime.now() + timedelta(seconds=10)
            yield UpdateExpectedCodesCount(update_time=update_time)
        else:
            yield event

    @staticmethod
    def _process_taskerror(event: TaskError) -> None:
        logger.error(f"При сканировании произошла ошибка: {event.message}")

    # noinspection PyUnusedLocal
    @staticmethod
    def _process_startscanning(event: StartScanning) -> None:
        logger.info(f"Процесс начал сканирование")

    # noinspection PyUnusedLocal
    @staticmethod
    def _process_endscanning(event: EndScanning) -> None:
        logger.info(f"Процесс завершил работу")

    def _process_packwithcodes(self, event: PackWithCodes) -> None:
        notify_about_packdata(
            self._domain_url,
            barcodes=event.barcodes,
            qr_codes=event.qr_codes,
        )

    # noinspection PyUnusedLocal
    @staticmethod
    def _process_packbadcodes(event: PackBadCodes) -> Iterable[BaseEvent]:
        yield OpenShutter()
        close_time = datetime.now() + timedelta(seconds=16)
        yield CloseShutter(close_time=close_time)

    # noinspection PyUnusedLocal
    @staticmethod
    def _process_open_discard(event: OpenShutter) -> None:
        send_shutter_down()

    # noinspection PyUnusedLocal
    @staticmethod
    def _process_close_discard(event: CloseShutter) -> Iterable[CloseShutter]:
        now = datetime.now()
        if now >= event.close_time:
            send_shutter_up()
        else:
            yield event


def setup_logger():
    log_path = os.getenv('LOG_PATH', 'logs/1camera.log')
    log_level = os.getenv('LOG_LEVEL', 'DEBUG')

    logger.add(sink=log_path, level=log_level, rotation='2 MB', compression='zip')


def collect_scanner_args() -> tuple:
    video_urls = os.getenv('VIDEO_URLS', 'video1.mp4;video2.mp4')
    display_window = os.getenv('DISPLAY_WINDOW', '1')
    auto_reconnect = os.getenv('AUTO_RECONNECT', '1')

    video_urls = video_urls.split(';')
    display_window = int(display_window) != 0
    auto_reconnect = int(auto_reconnect) != 0

    return (
        video_urls[0],
        display_window,
        auto_reconnect,
        tuple(),
    )


def run():
    """
    Готовит список аргументов, логер и запускает выполнение
    событийного цикла по обработке событий от сканера
    """
    domain_url = os.getenv('DOMAIN_URL', 'http://localhost')
    setup_logger()

    # аргументы для worker_task (кроме queue и worker_id) для запуска в разных процессах
    processes_args = collect_scanner_args()

    try:
        runner = RunnerWith1Camera(processes_args, domain_url)
        runner.mainloop_with_lock()
    except KeyboardInterrupt as e:
        logger.info(f"Выполнение прервано {e}")
    except BaseException as e:
        logger.critical("Падение с критической ошибкой")
        logger.opt(exception=e)
        raise e
