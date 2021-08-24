import os

from loguru import logger

from .communication.signals import get_pack_codes_count, notify_about_packdata, notify_bad_packdata
from .event_system.events import *
from .event_system.handling import EventProcessor
from .packs_processing import InstantCameraProcessingQueue
from .video_processing import get_events_from_video


class RunnerWith1Camera:
    def __init__(self, camera_args: tuple, domain_url: str):
        self._event_processor = EventProcessor()
        self._processing_queue = InstantCameraProcessingQueue()
        self._domain_url = domain_url
        self._expected_codes_count = 2
        self._iter_modcounter = 0
        self._camera_args = camera_args

        self._init_event_processor()

    def _init_event_processor(self):
        handlers = [
            self._process_camerapackresult,
            self._process_taskerror,
            self._process_startscanning,
            self._process_endscanning,
            self._process_packwithcodes,
            self._process_packbadcodes,
        ]
        for handler in handlers:
            self._event_processor.add_handler(handler)

    def _update_expected_codes_count(self) -> None:
        ITERATION_PER_REQUEST = 15
        if self._iter_modcounter != 0:
            return
        new_codes_count = get_pack_codes_count(self._domain_url)
        if new_codes_count is not None:
            self.expected_codes_count = new_codes_count
        self._iter_modcounter = (self._iter_modcounter + 1) % ITERATION_PER_REQUEST

    def mainloop_with_lock(self) -> None:
        """
        Запускает обработку QR- и штрихкодов с камеры,
        открывает блокирующий событийный цикл для обработки приходящих от неё событий.

        Отлавливает и логгирует доходящие до него некритичные исключения.

        Завершается при ``KeyboardInterrupt`` (Ctrl+C в терминале)
        """
        events_from_cam = get_events_from_video(*self._camera_args)

        for new_event in events_from_cam:
            try:
                self._update_expected_codes_count()
                self._event_processor.process_event(new_event)

                events = list(self._processing_queue.get_processed_latest())
                for event in events:
                    # тут происходит обработка событий из списка с событиями
                    # - вызывается подходящий метод self._process_*Событие*
                    self._event_processor.process_event(event)

            except KeyboardInterrupt as e:
                logger.info(f"Выполнение прервано {e}")
                break
            except Exception as e:
                logger.exception("Неотловленное исключение")
                logger.opt(exception=e)

    def _process_camerapackresult(self, event: CameraPackResult):
        msg = (f"Получены данные от камеры: "
               f"QR={event.qr_codes} "
               f"BAR={event.barcodes} "
               f"время пачки='{event.start_time} - {event.finish_time}'")
        logger.debug(msg)
        event.receive_time = datetime.now()
        event.expected_codes_count = self._expected_codes_count
        self._processing_queue.enqueue(event)

    @staticmethod
    def _process_taskerror(event: TaskError):
        event.receive_time = datetime.now()
        logger.error(f"При сканировании произошла ошибка: {event.message}")

    @staticmethod
    def _process_startscanning(event: StartScanning):
        event.receive_time = datetime.now()
        logger.info(f"Процесс начал сканирование")

    @staticmethod
    def _process_endscanning(event: EndScanning):
        event.receive_time = datetime.now()
        logger.info(f"Процесс завершил работу")

    # noinspection PyUnusedLocal
    def _process_packbadcodes(self, event: PackBadCodes):
        notify_bad_packdata(self._domain_url)

    def _process_packwithcodes(self, event: PackWithCodes):
        notify_about_packdata(
            self._domain_url,
            barcodes=event.barcodes,
            qr_codes=event.qr_codes,
        )


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
    except BaseException as e:
        logger.critical("Падение с критической ошибкой")
        logger.opt(exception=e)
        raise e
