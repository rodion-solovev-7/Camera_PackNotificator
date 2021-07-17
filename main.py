import logging
import os
from datetime import datetime, timedelta
from logging import Logger
from multiprocessing import Queue, Process
from typing import List, Callable, Iterable, Dict

import requests
from dotenv import load_dotenv

from camera_processing import event_iterator
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
    - В случае успешной обработки экземпляр ``TaskError`` со считанными данными.
    """

    events: Iterable[CamScannerEvent]
    events = event_iterator(video_url, model_path)

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
        log_level = logging.DEBUG
        message = f"Получены данные от процесса: {event}"
    elif isinstance(event, TaskError):
        log_level = logging.ERROR
        message = f"Отловленная ошибка в процессе: {event}"
    else:
        log_level = logging.ERROR
        message = f"Непредусмотренное событие от процесса: {event}"

    logger.log(level=log_level, msg=message)


def process_new_result(
        logger: Logger,
        results_by_process_id: Dict[int, List[TaskResult]],
        new_result: TaskResult,
        domain_url: str,
):
    """
    Анализирует последние данные от сканеров и отправляет нужный запрос на сервер.
    """

    url = f'{domain_url}/api/v1_0/new_pack_after_pintset'

    # время, за которое +- проезжает пачка (3-5 сек)
    STORE_TIME = timedelta(seconds=7)

    new_worker_id = new_result.worker_id
    opposite_worker_id = (new_worker_id + 1) % 2

    results = results_by_process_id[new_worker_id]
    results_opposite = results_by_process_id[opposite_worker_id]

    results.append(new_result)

    while min(len(results), len(results_opposite)) > 0:
        r1, r2 = results.pop(), results_opposite.pop()

        is_complete1 = r1.qr_code is not None and r1.barcode is not None
        is_complete2 = r2.qr_code is not None and r2.barcode is not None

        some_result = None
        if is_complete1 and not is_complete2:
            some_result = r1
        elif not is_complete1 and is_complete2:
            some_result = r2

        # TODO: пока что всё держится на вере, что рассинхрона между процессами не будет.
        #  Нужно добавить проверки на нестандартные случаи:
        #  смещение события в порядке 'прихода', дублирование событий, отсутствие события с одной из камер

        # TODO: определиться с тем, что отправлять при отсутствии обеих пачек

        if some_result is None:

            qr_code, barcode = None, None
        else:
            qr_code = some_result.qr_code
            barcode = some_result.barcode

        data = {
            'qr': qr_code,
            'barcode': barcode,
        }

        try:
            message = f"Отправка данных на сервер: {data}"
            logger.debug(msg=message)
            _ = requests.put(url, json=data, timeout=2)
        except Exception:
            logger.error("Аппликатор - нет Сети")


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
    queue = Queue()

    processes = get_started_processes(
        task=worker_task,
        queue=queue,
        processes_args=processes_args,
    )

    results_by_process_id: Dict[int, List[TaskResult]] = {
        i: [] for i in range(len(processes_args))
    }

    while True:
        try:
            event: CamScannerEvent = queue.get()
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
    model_path = os.getenv('MODEL_PATH')
    domain_url = os.getenv('DOMAIN_URL')
    video_urls_line = os.getenv('VIDEO_URLS')
    video_urls = video_urls_line.split(';')

    if len(video_urls) != 2:
        raise Exception("Данная программа рассчитана на 2 камеры. Ожидается ровно 2 адреса для подключения")

    logging.basicConfig(level='DEBUG', filename=log_path)
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
