"""
Главный файл программы.

Здесь происходит запуск и управление процессами, которые читают коды с камер,
получение от них данных, их синхронизация между собой и отправка запросов с финальными данными.

-----

Немного о задаче:
    - 2 камеры смотрят на продукцию с двух сторон
    - на продукции с одной из сторон есть QR-коды и штрих-коды и видит их только 1 камера из 2-ух
    - если с продукции прочитано кодов меньше ожидаемого числа, то нужно известить об ошибке
    - если на продукции есть коды и их нужное кол-во, то их нужно отправить серверу
    - изредка функции которые определяют, есть ли продукция на изображении, ошибаются -
      приходят данные с продукцией без кодов
    - ...
    - возможно ещё что-то, но я не помню
"""
import os
from multiprocessing import Queue, Process
from queue import Empty

from loguru import logger

from .communication.signals import get_pack_codes_count, notify_bad_packdata, notify_about_packdata
from .event_system.events import *
from .event_system.handling import EventProcessor
from .packs_processing import Interval2CamerasProcessingQueue
from .video_processing import get_events_from_video


class CameraScannerProcess(Process):
    """
    Процесс - обработчик событий с камеры.
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
            queue: Queue,
            worker_id: int,
            video_url: str,
            display_window: bool,
            auto_reconnect: bool,
            recognizer_args: tuple,
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
                recognizer_args=recognizer_args,
            )

            # бесконечный цикл, который получает события от камеры и кладёт их в очередь
            for event in events:
                event.worker_id = worker_id
                event.receive_time = None

                # отправка события основному процессу
                queue.put(event)
        except KeyboardInterrupt:
            pass


class RunnerWith2Cameras:
    _queue: Queue
    _processes: list[Process]

    def __init__(self, processes_args: list[tuple], domain_url: str):
        self._queue = Queue()
        self._sync_queue = Interval2CamerasProcessingQueue()
        self._event_processor = EventProcessor()
        self._processes = self._get_processes(processes_args)
        self._domain_url = domain_url
        self._expected_codes_count = 2
        self._iter_modcounter = 0

        self._init_event_processor()

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

    def _get_event_from_cam(self) -> Optional[CamScannerEvent]:
        QUEUE_REQUEST_TIMEOUT_SEC = 1.5
        try:
            event = self._queue.get(timeout=QUEUE_REQUEST_TIMEOUT_SEC)
            return event
        except Empty:
            return None

    def mainloop_with_lock(self) -> None:
        """
        Запускает процессы обработки QR- и штрихкодов с камер,
        открывает блокирующий событийный цикл для обработки приходящих от них событий.

        Отлавливает и логгирует доходящие до него некритичные исключения.

        Завершается при ``KeyboardInterrupt`` (Ctrl+C в терминале)
        """
        self._run_processes()

        while True:
            try:
                self._update_expected_codes_count()
                events = list(self._sync_queue.get_processed_latest())

                event = self._get_event_from_cam()
                if event is not None:
                    events.append(event)

                for event in events:
                    # тут происходит обработка событий из списка с событиями
                    # - вызывается подходящий метод self._process_*Событие*
                    self._event_processor.process_event(event)

            except KeyboardInterrupt as e:
                logger.info(f"Выполнение прервано {e}")
                self._kill_processes()
                break
            except Exception as e:
                logger.exception("Неотловленное исключение")
                logger.opt(exception=e)

    def _process_camerapackresult(self, event: CameraPackResult):
        msg = (f"Получены данные от процесса #{event.worker_id}: "
               f"QR={event.qr_codes} "
               f"BAR={event.barcodes} "
               f"время пачки='{event.start_time} - {event.finish_time}'")
        logger.debug(msg)
        event.receive_time = datetime.now()
        event.is_paired = False
        event.expected_codes_count = self._expected_codes_count
        self._sync_queue.enqueue(event)

    @staticmethod
    def _process_taskerror(event: TaskError):
        event.receive_time = datetime.now()
        logger.error(f"В процессе #{event.worker_id} "
                     f"произошла ошибка: {event.message}")

    @staticmethod
    def _process_startscanning(event: StartScanning):
        event.receive_time = datetime.now()
        logger.info(f"Процесс #{event.worker_id} начал сканирование")

    def _process_endscanning(self, event: EndScanning):
        event.receive_time = datetime.now()
        logger.info(f"Процесс #{event.worker_id} завершил работу")

        process = self._processes[event.worker_id]
        process.terminate()
        process.join()

        alive_count = sum(process.is_alive() for process in self._processes)
        if alive_count == 0:
            raise KeyboardInterrupt("Все процессы завершили работу. Закрытие программы")

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
    log_path = os.getenv('LOG_PATH', 'logs/2cameras.log')
    log_level = os.getenv('LOG_LEVEL', 'DEBUG')

    logger.add(sink=log_path, level=log_level, rotation='2 MB', compression='zip')


def collect_scanners_args() -> list[tuple]:
    video_urls = os.getenv('VIDEO_URLS', 'video1.mp4;video2.mp4')
    display_window = os.getenv('DISPLAY_WINDOW', '1')
    auto_reconnect = os.getenv('AUTO_RECONNECT', '1')

    video_urls = video_urls.split(';')
    display_window = int(display_window) != 0
    auto_reconnect = int(auto_reconnect) != 0

    if len(video_urls) != 2:
        message = ("Данная программа рассчитана на 2 камеры. "
                   "В .env через ';' ожидается ровно 2 адреса для подключения.")
        raise ValueError(message)

    return [
        (
            video_url,
            display_window,
            auto_reconnect,
            tuple(),
        ) for video_url in video_urls
    ]


def run():
    """
    Готовит список аргументов, логер и запускает выполнение
    событийного цикла по обработке событий процессов-сканеров.
    """
    domain_url = os.getenv('DOMAIN_URL', 'http://localhost')
    setup_logger()

    # аргументы для worker_task (кроме queue и worker_id) для запуска в разных процессах
    processes_args = collect_scanners_args()

    try:
        runner = RunnerWith2Cameras(processes_args, domain_url)
        runner.mainloop_with_lock()
    except BaseException as e:
        logger.critical("Падение с критической ошибкой")
        logger.opt(exception=e)
        raise e
