import multiprocessing as mp
from datetime import datetime, timedelta
from queue import Empty
from time import sleep
from typing import Optional

from loguru import logger

from .communication.signals import (get_pack_codes_count, notify_about_packdata,
                                    send_shutter_down, send_shutter_up)
from .events import *
from .events.handling import *
from .packs_processing import InstantCameraProcessingQueue, Interval2CamerasProcessingQueue
from .video_processing import CameraScannerProcess


# noinspection PyPep8Naming
class SingleCameraWorker(EventWorker):
    start_events = [
        UpdateExpectedCodesCount(update_time=datetime.now()),
        ReadEventFromProcessQueue(),
        ReadResultsFromValidationQueue(read_time=datetime.now()),
        Wait(),
    ]

    def __init__(self, cameras_args: list[tuple], domain_url: str):
        self._queue = mp.Queue()
        self._cam_validating_queue = InstantCameraProcessingQueue()
        self._domain_url = domain_url
        self._expected_codes_count = 2
        self._cameras_args = cameras_args[:1]
        self._processes = self._get_processes(self._cameras_args)
        super().__init__()
        self.set_event_handlers()
        self.set_start_events()

    def set_event_handlers(self):
        import inspect
        methods = inspect.getmembers(self, predicate=inspect.ismethod)
        self.handlers = [method for name, method in methods
                         if name.startswith('_process_')]
        super().set_event_handlers()

    def run_processing(self) -> None:
        self._run_processes()
        while len(self._event_processing_queue) > 0:
            try:
                self._event_processing_queue.process_latest()
            except KeyboardInterrupt as e:
                self._kill_processes()
                raise e
            except Exception as e:
                logger.error("Неотловленное исключение")
                logger.opt(exception=e)

    def _get_processes(self, processes_args: list[tuple]) -> list[CameraScannerProcess]:
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

    def _get_event_from_cam(self) -> Optional[CamScannerEvent]:
        QUEUE_REQUEST_TIMEOUT_SEC = 1.5
        try:
            event = self._queue.get(timeout=QUEUE_REQUEST_TIMEOUT_SEC)
            return event
        except Empty:
            return None

    def _update_expected_codes_count(self) -> None:
        new_codes_count = get_pack_codes_count(self._domain_url)
        if new_codes_count is not None:
            self.expected_codes_count = new_codes_count

    # обработчики событий

    def _process_CameraPackResult(self, event: CameraPackResult) -> list[BaseEvent]:
        msg = (f"Получены данные от камеры: "
               f"QR={event.qr_codes} "
               f"BAR={event.barcodes} "
               f"время пачки='{event.start_time} - {event.finish_time}'")
        logger.debug(msg)
        event.receive_time = datetime.now()
        event.expected_codes_count = self._expected_codes_count
        self._cam_validating_queue.enqueue(event)
        return self._cam_validating_queue.get_processed_latest()

    def _process_UpdateExpectedCodesCount(
            self,
            event: UpdateExpectedCodesCount,
    ) -> UpdateExpectedCodesCount:
        now = datetime.now()
        if now < event.update_time:
            return event
        self._update_expected_codes_count()
        update_time = datetime.now() + timedelta(seconds=10)
        return UpdateExpectedCodesCount(update_time=update_time)

    @staticmethod
    def _process_TaskError(event: TaskError) -> None:
        logger.error(f"При сканировании произошла ошибка: {event.message}")

    @staticmethod
    def _process_StartScanning(event: StartScanning) -> None:
        logger.info(f"Процесс #{event.worker_id} начал сканирование")

    @staticmethod
    def _process_EndScanning(event: EndScanning) -> None:
        logger.info(f"Процесс #{event.worker_id} завершил работу")

    def _process_PackWithCodes(self, event: PackWithCodes) -> None:
        notify_about_packdata(
            self._domain_url,
            barcodes=event.barcodes,
            qr_codes=event.qr_codes,
        )

    def _process_ReadEventFromProcessQueue(
            self,
            event: ReadEventFromProcessQueue,
    ) -> tuple[ReadEventFromProcessQueue, Optional[CamScannerEvent]]:
        new_event = self._get_event_from_cam()
        return event, new_event

    # noinspection PyUnusedLocal
    @staticmethod
    def _process_PackBadCodes(event: PackBadCodes) -> tuple[OpenGate, CloseGate]:
        open_time = datetime.now() + timedelta(seconds=2)
        close_time = datetime.now() + timedelta(seconds=16)
        return OpenGate(open_time=open_time), CloseGate(close_time=close_time)

    @staticmethod
    def _process_OpenGate(event: OpenGate) -> Optional[OpenGate]:
        now = datetime.now()
        if now < event.open_time:
            return event
        send_shutter_down()

    @staticmethod
    def _process_CloseGate(event: CloseGate) -> Optional[CloseGate]:
        now = datetime.now()
        if now < event.close_time:
            return event
        send_shutter_up()

    def _process_ReadResultsFromSyncQueue(
            self, event: ReadResultsFromValidationQueue,
    ) -> list[BaseEvent]:
        now = datetime.now()
        if now < event.read_time:
            return [event]
        results = self._cam_validating_queue.get_processed_latest()
        read_time = now + timedelta(seconds=8)
        event = ReadResultsFromValidationQueue(read_time=read_time)
        return results + [event]

    @staticmethod
    def _process_Wait(event: Wait) -> Wait:
        sleep(5)
        return event


# noinspection PyPep8Naming
class DuoCamerasWorker(EventWorker):
    start_events = [
        UpdateExpectedCodesCount(update_time=datetime.now()),
        ReadEventFromProcessQueue(),
        ReadResultsFromValidationQueue(read_time=datetime.now()),
        Wait(),
    ]

    def __init__(self, cameras_args: list[tuple], domain_url: str):
        self._queue = mp.Queue()
        self._cam_sync_queue = Interval2CamerasProcessingQueue()
        self._domain_url = domain_url
        self._expected_codes_count = 2
        self._cameras_args = cameras_args[:2]
        self._processes = self._get_processes(self._cameras_args)
        super().__init__()
        self.set_event_handlers()
        self.set_start_events()

    def set_event_handlers(self):
        import inspect
        methods = inspect.getmembers(self, predicate=inspect.ismethod)
        self.handlers = [method for name, method in methods
                         if name.startswith('_process_')]
        super().set_event_handlers()

    def run_processing(self) -> None:
        self._run_processes()
        while len(self._event_processing_queue) > 0:
            try:
                self._event_processing_queue.process_latest()
            except KeyboardInterrupt as e:
                self._kill_processes()
                raise e
            except Exception as e:
                logger.error("Неотловленное исключение")
                logger.opt(exception=e)

    def _get_processes(self, processes_args: list[tuple]) -> list[CameraScannerProcess]:
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

    def _get_event_from_cam(self) -> Optional[CamScannerEvent]:
        QUEUE_REQUEST_TIMEOUT_SEC = 1.5
        try:
            event = self._queue.get(timeout=QUEUE_REQUEST_TIMEOUT_SEC)
            return event
        except Empty:
            return None

    def _update_expected_codes_count(self) -> None:
        new_codes_count = get_pack_codes_count(self._domain_url)
        if new_codes_count is not None:
            self.expected_codes_count = new_codes_count

    # обработчики событий

    def _process_CameraPackResult(self, event: CameraPackResult) -> list[BaseEvent]:
        msg = (f"Получены данные от камеры: "
               f"QR={event.qr_codes} "
               f"BAR={event.barcodes} "
               f"время пачки='{event.start_time} - {event.finish_time}'")
        logger.debug(msg)
        event.receive_time = datetime.now()
        event.expected_codes_count = self._expected_codes_count
        self._cam_sync_queue.enqueue(event)
        return self._cam_sync_queue.get_processed_latest()

    def _process_UpdateExpectedCodesCount(
            self,
            event: UpdateExpectedCodesCount,
    ) -> UpdateExpectedCodesCount:
        now = datetime.now()
        if now < event.update_time:
            return event
        self._update_expected_codes_count()
        update_time = datetime.now() + timedelta(seconds=10)
        return UpdateExpectedCodesCount(update_time=update_time)

    @staticmethod
    def _process_TaskError(event: TaskError) -> None:
        logger.error(f"При сканировании произошла ошибка: {event.message}")

    @staticmethod
    def _process_StartScanning(event: StartScanning) -> None:
        logger.info(f"Процесс #{event.worker_id} начал сканирование")

    @staticmethod
    def _process_EndScanning(event: EndScanning) -> None:
        logger.info(f"Процесс #{event.worker_id} завершил работу")

    def _process_PackWithCodes(self, event: PackWithCodes) -> None:
        notify_about_packdata(
            self._domain_url,
            barcodes=event.barcodes,
            qr_codes=event.qr_codes,
        )

    def _process_ReadPacksFromQueue(
            self,
            event: ReadEventFromProcessQueue,
    ) -> tuple[ReadEventFromProcessQueue, Optional[CamScannerEvent]]:
        new_event = self._get_event_from_cam()
        return event, new_event

    # noinspection PyUnusedLocal
    @staticmethod
    def _process_PackBadCodes(event: PackBadCodes) -> tuple[OpenGate, CloseGate]:
        open_time = datetime.now() + timedelta(seconds=2)
        close_time = datetime.now() + timedelta(seconds=16)
        return OpenGate(open_time=open_time), CloseGate(close_time=close_time)

    @staticmethod
    def _process_OpenGate(event: OpenGate) -> Optional[OpenGate]:
        now = datetime.now()
        if now < event.open_time:
            return event
        send_shutter_down()

    @staticmethod
    def _process_CloseGate(event: CloseGate) -> Optional[CloseGate]:
        now = datetime.now()
        if now < event.close_time:
            return event
        send_shutter_up()

    def _process_ReadResultsFromValidationQueue(
            self,
            event: ReadResultsFromValidationQueue,
    ) -> list[BaseEvent]:
        now = datetime.now()
        if now < event.read_time:
            return [event]
        results = self._cam_sync_queue.get_processed_latest()
        read_time = now + timedelta(seconds=8)
        event = ReadResultsFromValidationQueue(read_time=read_time)
        return results + [event]

    @staticmethod
    def _process_Wait(event: Wait) -> Wait:
        sleep(5)
        return event
