import os
from collections import deque
from datetime import datetime, timedelta
from multiprocessing import Queue, Process
from queue import Empty
from typing import List, Callable, Iterable, Deque, Optional, Type

import requests
from dotenv import load_dotenv
from loguru import logger

from camera_processing import get_events
from worker_events import TaskResult, CamScannerEvent, TaskError, EndScanning, StartScanning


def worker_task(
        queue: Queue,
        worker_id: int,
        video_url: str,
        model_path: str,
        display_window: bool,
        auto_reconnect: bool,
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
        video_url=video_url,
        model_path=model_path,
        display_window=display_window,
        auto_reconnect=auto_reconnect,
    )

    # бесконечный цикл, который получает события от конкретной камеры
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
        if not process.is_alive():
            continue
        process.terminate()
        process.join()


def process_event(
        event: Type[CamScannerEvent],
        results_by_process_id: List[Deque[TaskResult]],
        processes: List[Process],
        domain_url: str,
        expected_codes_count: int,
):
    """
    Обрабатывает событие от процесса сканирования.
    Логирует это событие, если необходимо.
    """
    if isinstance(event, TaskResult):
        message = (f"Получены данные от процесса #{event.worker_id}: "
                   f"QR={event.qr_codes} "
                   f"BAR={event.barcodes} "
                   f"время конца пачки='{event.finish_time}'")
        logger.debug(message)
        process_new_result(
            results_by_process_id,
            event,
            domain_url,
            expected_codes_count,
        )
    elif isinstance(event, TaskError):
        message = (f"В процессе #{event.worker_id} "
                   f"произошла ошибка: {event.message}")
        logger.info(message)
    elif isinstance(event, StartScanning):
        message = f"Процесс #{event.worker_id} начал сканирование"
        logger.info(message)
    elif isinstance(event, EndScanning):
        message = f"Процесс #{event.worker_id} завершил работу"
        logger.info(message)

        process = processes[event.worker_id]
        process.terminate()
        process.join()
        alive_count = sum(process.is_alive() for process in processes)
        if alive_count == 0:
            raise GeneratorExit("Все процессы завершили работу. Закрытие программы")
    else:
        message = f"Для события не написан обработчик: {event}"
        logger.warning(message)


def process_new_result(
        results_by_process_id: List[Deque[TaskResult]],
        new_result: TaskResult,
        domain_url: str,
        expected_codes_count: int,
):
    """
    Обрабатывает полученные от сканера QR- и шрихкоды,
    анализирует последние данные и отправляет нужный запрос на сервер.

    (Ожидает ровно 2 запущенных процесса сканирования!)
    """

    # время, за которое +- проезжает пачка (3-5 сек)
    STORE_TIME = timedelta(seconds=7)

    new_worker_id = new_result.worker_id
    opposite_worker_id = (new_worker_id + 1) % 2

    events1 = results_by_process_id[new_worker_id]
    events2 = results_by_process_id[opposite_worker_id]

    events1.append(new_result)

    while min(len(events1), len(events2)) > 0:
        r1, r2 = events1.popleft(), events2.popleft()

        # TODO: пока что всё держится на вере, что рассинхрона между процессами не будет.
        #  Здесь стоит добавить проверки на нестандартные случаи:
        #  смещение события в порядке 'прихода', разделение событий
        #  (вместо 2 кодов в одном событии пришло 2 события по 1 коду),
        #  отсутствие события с одной из камер

        is_complete1 = (len(r1.qr_codes) == expected_codes_count and
                        len(r1.barcodes) == expected_codes_count)
        is_complete2 = (len(r2.qr_codes) == expected_codes_count and
                        len(r2.barcodes) == expected_codes_count)

        success_result: Optional[TaskResult] = None

        if is_complete1 and is_complete2:
            # TODO: очень странный и редкий случай:
            #  возможно, тут нужны будут доп. проверки
            success_result = r1

            message = "QR- и штрихкоды обнаружены с обеих сторон пачки"
            logger.info(message)

        elif is_complete1 or is_complete2:
            success_result = r1 if is_complete1 else r2

            message = "На одной из сторон пачки обнаружены QR- и штрихкоды"
            logger.debug(message)

        elif not is_complete1 and not is_complete2:
            success_result = None

            message = "QR- и штрихкодов нет с обеих сторон пачки"
            logger.info(message)

        if success_result is None:
            notify_that_no_packdata(domain_url)
        else:
            notify_about_packdata(domain_url, success_result)


def notify_about_packdata(
        domain_url: str,
        result: TaskResult,
):
    """
    Оповещает сервер, что QR- и штрихкоды успешно считаны с пачки.
    Считанные данные также отправляются серверу.
    """

    success_pack_mapping = f'{domain_url}/api/v1_0/new_pack_after_pintset'
    REQUEST_TIMEOUT_SEC = 2

    for qr_code, barcode in zip(result.qr_codes, result.barcodes):
        send_data = {
            'qr': qr_code,
            'barcode': barcode,
        }

        try:
            message = f"Отправка данных пачки на сервер: {send_data}"
            logger.debug(message)
            _ = requests.put(success_pack_mapping, json=send_data, timeout=REQUEST_TIMEOUT_SEC)
        except Exception:
            logger.error("Аппликатор - нет Сети")


def notify_that_no_packdata(domain_url: str):
    """
    Оповещает сервер, что QR- и штрихкоды не были считаны с текущей пачки.
    """
    # TODO: ниже должен быть url для отправки запросов о пачке без QR- и штрихкодов
    empty_pack_mapping = f'{domain_url}/api/v1_0/!!!__TODO__FILLME__!!!'
    REQUEST_TIMEOUT_SEC = 2

    try:
        message = "Отправка извещения о пачке без данных на сервер"
        logger.debug(message)

        # TODO: ниже (вместо warning'а) должен быть запрос к серверу для случая,
        #  когда с обеих сторон пачки не обнаружено кодов
        logger.warning("ЗАПРОС НЕ РЕАЛИЗОВАН")

    except Exception:
        logger.error("Аппликатор - нет Сети")


def get_work_mode(domain_url: str) -> Optional[str]:
    """
    Получает режим работы (в оригинале "записи"!?) с сервера.
    """
    wmode_mapping = f'{domain_url}/api/v1_0/get_mode'
    REQUEST_TIMEOUT_SEC = 2

    try:
        message = "Получение данных о текущем режиме записи"
        logger.debug(message)
        response = requests.get(wmode_mapping, timeout=REQUEST_TIMEOUT_SEC)
        wmode = response.json()['work_mode']
        return wmode
    except Exception:
        logger.error("Аппликатор - нет Сети")
        return None


def get_pack_codes_count(domain_url: str, prev_value: int) -> Optional[int]:
    """
    Узнаёт от сервера, сколько QR-кодов ожидать на одной пачке
    """
    # TODO: ниже должен быть url для получения кол-ва qr-кодов с сервера
    qr_count_mapping = f'{domain_url}/api/v1_0/!!__TODO_FILLME__!!'
    REQUEST_TIMEOUT_SEC = 2

    try:
        message = "Получение данных об ожидаемом кол-ве QR-кодов"
        logger.debug(message)

        # TODO: ниже (вместо warning'а) должен быть запрос к серверу
        #  для определения кол-ва кодов в пачке
        logger.warning("ЗАПРОС НЕ РЕАЛИЗОВАН")
        return 1

    except Exception:
        logger.error("Аппликатор - нет Сети")
        return prev_value


def run_parent_event_loop(
        processes_args: List[tuple],
        domain_url: str,
):
    """
    Запускает процессы обработки QR- и штрихкодов с камер,
    открывает блокирующий событийный цикл для обработки приходящих от них событий.

    Отлавливает и логгирует доходящие до него некритичные исключения.

    Завершается при ``KeyboardInterrupt`` (Ctrl+C в терминале)
    """
    QUEUE_REQUEST_TIMEOUT_SEC = 1.5
    ITERATION_PER_REQUEST = 15

    queue = Queue()
    processes = get_started_processes(
        task=worker_task,
        queue=queue,
        processes_args=processes_args,
    )

    results_by_process_id: List[Deque[TaskResult]] = [
        deque() for _, _ in enumerate(processes_args)
    ]

    expected_codes_count = 1

    iteration_count = 0
    while True:
        try:
            if iteration_count == 0:
                expected_codes_count = get_pack_codes_count(domain_url, prev_value=expected_codes_count)
            iteration_count = (iteration_count + 1) % ITERATION_PER_REQUEST

            try:
                event: Type[CamScannerEvent] = queue.get(timeout=QUEUE_REQUEST_TIMEOUT_SEC)
            except Empty:
                continue
            event.receive_time = datetime.now()

            process_event(
                event,
                results_by_process_id,
                processes,
                domain_url,
                expected_codes_count,
            )

        except KeyboardInterrupt:
            message = "Выполнение прервано пользователем. Закрытие!"
            logger.info(message)
            kill_processes(processes)
            break
        except GeneratorExit as e:
            message = f"Выполнение прервано из-за: '{e}'"
            logger.info(message)
            break
        except Exception as e:
            message = "Неотловленное исключение"
            logger.exception(message)
            logger.opt(exception=e)


def main():
    """
    Готовит список аргументов, логер и запускает выполнение
    событийного цикла по обработке событий процессов-сканеров.
    """
    load_dotenv()
    log_path = os.getenv('LOG_PATH', 'cameras.log')
    log_level = os.getenv('LOG_LEVEL', 'TRACE')
    model_path = os.getenv('MODEL_PATH')
    domain_url = os.getenv('DOMAIN_URL')
    video_urls = os.getenv('VIDEO_URLS')
    display_window = os.getenv('DISPLAY_WINDOW', '1')
    auto_reconnect = os.getenv('AUTO_RECONNECT', '1')

    video_urls = video_urls.split(';')
    display_window = int(display_window) == 1
    auto_reconnect = int(auto_reconnect) == 1

    if len(video_urls) != 2:
        message = ("Данная программа рассчитана на 2 камеры. "
                   "В .env через ';' ожидается ровно 2 адреса для подключения.")
        raise ValueError(message)

    logger.add(sink=log_path, level=log_level)

    # аргументы для worker_task (кроме queue и worker_id) для запуска в разных процессах
    processes_args = [
        (
            video_url,
            model_path,
            display_window,
            auto_reconnect,
        ) for video_url in video_urls
    ]

    try:
        run_parent_event_loop(processes_args, domain_url)
    except BaseException as e:
        message = "Падение с критической ошибкой"
        logger.critical(message)
        logger.opt(exception=e)
        raise e


if __name__ == '__main__':
    main()
