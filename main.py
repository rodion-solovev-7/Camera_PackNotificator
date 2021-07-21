import logging
import os
from collections import deque
from datetime import datetime, timedelta
from logging import Logger
from multiprocessing import Queue, Process
from queue import Empty
from typing import List, Callable, Iterable, Deque, Optional

import requests
from dotenv import load_dotenv

from camera_processing import get_events
from worker_events import TaskResult, CamScannerEvent, TaskError


def worker_task(
        queue: Queue,
        worker_id: int,
        video_url: str,
        model_path: str,
) -> None:
    """
    Метод для запуска в отдельном процессе.

    Бесконечное читает QR-, штрихкоды с выбранной камеры
    и отправляет их данные базовому процессу через ``queue``.

    Кладёт в ``queue`` следующие события-наследники от ``CamScannerEvent``:

    - В случае ошибок экземпляр ``TaskError`` с информацией об ошибке.
    - В случае успешной обработки экземпляр ``TaskResult`` со считанными данными.
    """

    events: Iterable[CamScannerEvent]
    events = get_events(
        video_url,
        model_path,
        display=True,
        auto_reconnect=True,
    )

    # бесконечный цикл, который получает коды с конкретной камеры
    start_time = datetime.now()
    for event in events:
        event.worker_id = worker_id
        event.start_time = start_time
        event.receive_time = None

        # отправка события основному процессу
        queue.put(event)

        start_time = datetime.now()


def get_started_processes(
        task: Callable[[Queue, int], None],
        queue: Queue,
        processes_args: List[tuple],
) -> List[Process]:
    """
    Инициализирует процессы с выполнением выбранного ``task``'а.
    В качестве аргументов передаёт каждому очередь для коммуникации,
    их порядковый номер и пользовательские наборы аргументов.

    Возвращает список уже запущенных процессов.
    """
    processes = []
    for worker_id, args in enumerate(processes_args):
        process = Process(
            target=task,
            args=(queue, worker_id) + args,
            daemon=True,
        )
        process.start()
        processes.append(process)
    return processes


def kill_processes(processes: List[Process]) -> None:
    """Убивает процессы из списка"""
    for process in processes:
        process.terminate()


def log_event(logger: Logger, event: CamScannerEvent):
    """Логгирует пришедшее от процессе событие с необходимым уровнем"""
    if isinstance(event, TaskResult):
        message = f"Получены данные от процесса: {event}"
    elif isinstance(event, TaskError):
        message = f"Отловленная ошибка в процессе: {event}"
    else:
        message = f"Непредусмотренное событие от процесса: {event}"

    logger.log(level=event.LOG_LEVEL, msg=message)


def process_new_result(
        logger: Logger,
        results_by_process_id: List[Deque[TaskResult]],
        new_result: TaskResult,
        domain_url: str,
):
    """
    Анализирует последние данные от сканеров и отправляет нужный запрос на сервер.
    """

    # время, за которое +- проезжает пачка (3-5 сек)
    STORE_TIME = timedelta(seconds=7)

    assert len(results_by_process_id) == 2, ("Поддерживается обработка "
                                             "только 2-ух процессов сканирования")

    new_worker_id = new_result.worker_id
    opposite_worker_id = (new_worker_id + 1) % 2

    events1 = results_by_process_id[new_worker_id]
    events2 = results_by_process_id[opposite_worker_id]

    events1.append(new_result)

    while min(len(events1), len(events2)) > 0:
        r1, r2 = events1.popleft(), events2.popleft()

        # TODO: пока что всё держится на вере, что рассинхрона между процессами не будет.
        #  Здесь стоит добавить проверки на нестандартные случаи:
        #  смещение события в порядке 'прихода', дублирование событий,
        #  отсутствие события с одной из камер

        is_complete1 = r1.qr_code is not None and r1.barcode is not None
        is_complete2 = r2.qr_code is not None and r2.barcode is not None

        success_result: Optional[TaskResult] = None

        if is_complete1 and is_complete2:
            # TODO: очень странный и редкий случай:
            #  возможно, тут нужны будут доп. проверки
            success_result = r1

            message = "QR- и штрихкоды обнаружены с обеих сторон пачки"
            logger.info(msg=message)

        elif is_complete1 or is_complete2:
            success_result = r1 if is_complete1 else r2

            message = "На одной из сторон пачки обнаружены QR- и штрихкоды"
            logger.debug(msg=message)

        elif not is_complete1 and not is_complete2:
            success_result = None

            message = "QR- и штрихкодов нет с обеих сторон пачки"
            logger.info(msg=message)

        if success_result is None:
            notify_that_no_packdata(logger, domain_url)
        else:
            notify_about_packdata(logger, domain_url, success_result)


def notify_about_packdata(logger: Logger, domain_url: str, result: TaskResult):
    """
    Оповещает сервер, что QR- и штрихкоды успешно считаны с пачки.
    Считанные данные также отправляются серверу.
    """

    success_pack_mapping = f'{domain_url}/api/v1_0/new_pack_after_pintset'
    REQUEST_TIMEOUT_SEC = 2

    data = {
        'qr': result.qr_code,
        'barcode': result.barcode,
    }

    try:
        message = f"Отправка данных пачки на сервер: {data}"
        logger.debug(msg=message)
        _ = requests.put(success_pack_mapping, json=data, timeout=REQUEST_TIMEOUT_SEC)
    except Exception:
        logger.error("Аппликатор - нет Сети")


def notify_that_no_packdata(logger: Logger, domain_url: str):
    """
    Оповещает сервер, что QR- и штрихкоды не были считаны с текущей пачки.
    """
    # TODO: ниже должен быть url для отправки запросов о пачке без QR- и штрихкодов
    empty_pack_mapping = f'{domain_url}/api/v1_0/!!!__TODO__FILLME__!!!'
    REQUEST_TIMEOUT_SEC = 2

    try:
        message = "Отправка извещения о пачке без данных на сервер"
        logger.debug(msg=message)
        # TODO: ниже (вместо warning'а) должен быть запрос к серверу для случая,
        #  когда с обеих сторон пачки не обнаружено кодов
        logger.warning(msg="ЗАПРОС НЕ РЕАЛИЗОВАН")
    except Exception:
        logger.error("Аппликатор - нет Сети")


def get_work_mode_from_server(logger: Logger, domain_url: str) -> Optional[str]:
    """
    Получает режим работы (в оригинале "записи"!?) с сервера.
    """
    get_wmode_mapping = f'{domain_url}/api/v1_0/get_mode'
    REQUEST_TIMEOUT_SEC = 2

    try:
        message = "Получение данных о текущем режиме записи"
        logger.debug(msg=message)
        response = requests.get(get_wmode_mapping, timeout=REQUEST_TIMEOUT_SEC)
        wmode = response.json()['work_mode']
        return wmode
    except Exception:
        logger.error("Аппликатор - нет Сети")
        return None


def get_qr_in_one_pack_from_server(logger: Logger, domain_url: str) -> Optional[int]:
    """
    Узнаёт от сервера, сколько QR-кодов ожидать на одной пачке
    """
    # TODO: ниже должен быть url для получения кол-ва qr-кодов с сервера
    get_qr_count_mapping = f'{domain_url}/api/v1_0/!!__TODO_FILLME__!!'
    REQUEST_TIMEOUT_SEC = 2

    try:
        message = "Получение данных об ожидаемом кол-ве QR-кодов"
        logger.debug(msg=message)
        # TODO: ниже (вместо warning'а) должен быть запрос к серверу
        #  для определения кол-ва кодов в пачке
        logger.warning(msg="ЗАПРОС НЕ РЕАЛИЗОВАН")
        return None
    except Exception:
        logger.error("Аппликатор - нет Сети")
        return None


def parent_event_loop(
        logger: Logger,
        processes_args: List[tuple],
        domain_url: str,
):
    """
    Запускает процессы с обработкой QR- и штрихкоды,
    открывает блокирующий событийный цикл для обработки приходящих от них событий.

    Отлавливает и логгирует доходящие до него некритичные исключения.

    Завершается при ``KeyboardInterrupt`` (Ctrl+C в терминале)
    """
    QUEUE_REQUEST_TIMEOUT_SEC = 1.5

    queue = Queue()
    processes = get_started_processes(
        task=worker_task,
        queue=queue,
        processes_args=processes_args,
    )

    results_by_process_id: List[Deque[TaskResult]] = [
        deque() for _, _ in enumerate(processes_args)
    ]

    while True:
        try:
            # TODO: здесь должно быть получение и обработка ожидаемого кол-ва пачек с сервера

            try:
                event: CamScannerEvent = queue.get(timeout=QUEUE_REQUEST_TIMEOUT_SEC)
            except Empty:
                continue

            event.receive_time = datetime.now()

            log_event(logger, event)

            if isinstance(event, TaskResult):
                process_new_result(logger, results_by_process_id, event, domain_url)

        except KeyboardInterrupt:
            message = "Выполнение прервано пользователем. Закрытие!"
            logger.info(message)
            kill_processes(processes)
            break
        except Exception as e:
            message = "Неотловленное исключение"
            logger.exception(msg=message, exc_info=e)


def main():
    """
    Готовит список аргументов, логер и запускает выполнение
    событийного цикла по управлению данными QR- и штрихкодов.
    """

    load_dotenv()
    log_path = os.getenv('LOG_PATH')
    log_level = os.getenv('LOG_LEVEL')
    model_path = os.getenv('MODEL_PATH')
    domain_url = os.getenv('DOMAIN_URL')
    video_urls_line = os.getenv('VIDEO_URLS')
    video_urls = video_urls_line.split(';')

    if len(video_urls) != 2:
        message = ("Данная программа рассчитана на 2 камеры. "
                   "В .env через ';' ожидается ровно 2 адреса для подключения.")
        raise ValueError(message)

    logging.basicConfig(level=log_level, filename=log_path)
    logger = logging.getLogger(__name__)

    # аргументы для worker_task (кроме queue и worker_id) для запуска в разных процессах
    processes_args = [
        (video_url, model_path) for video_url in video_urls
    ]

    try:
        parent_event_loop(logger, processes_args, domain_url)
    except BaseException as e:
        message = "Падение с критической ошибкой"
        logger.critical(msg=message, exc_info=e)
        raise e


if __name__ == '__main__':
    main()
