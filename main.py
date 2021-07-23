import os
from collections import deque
from datetime import datetime, timedelta
from itertools import takewhile
from multiprocessing import Queue, Process
from operator import attrgetter
from queue import Empty
from typing import List, Callable, Iterable, Deque, Optional, Type

import requests
from dotenv import load_dotenv
from loguru import logger
# noinspection PyUnresolvedReferences
from requests import ConnectTimeout

from camera_processing import get_events
from event_handling import EventProcessor
from events import TaskResult, CamScannerEvent, TaskError, EndScanning, StartScanning


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


def enqueue_new_result(
        results_by_process_id: List[Deque[TaskResult]],
        new_result: TaskResult,
) -> None:
    """
    Обрабатывает полученную от сканера запись с QR- и шрихкодами.
    Добавляет её в очередь для сопоставления.
    """
    new_worker_id = new_result.worker_id
    results = results_by_process_id[new_worker_id]
    results.append(new_result)


def process_latest_results(
        results_by_process_id: List[Deque[TaskResult]],
        domain_url: str,
) -> None:
    """
    Анализирует последние результаты от камер из буффера обработки:

    - сопоставляет данные от двух камер
    - логгирует сомнительные ситуации
    - отправляет данные непустых пачек на сервер
    - для пустых с обеих сторон пачек извещает об отсутствии кода
    - отправляет нужные запросы на сервер
    - удаляет устаревшие записи
    """
    assert len(results_by_process_id) == 2, "Ожидается ровно 2 запущенных процесса сканирования!"

    MAX_CAMERAS_DIFF_TIME = timedelta(seconds=4)
    """
    Максимальная разница во времени проезда 
    одной и той же пачки на разных камерах.
    """

    RESULT_TIMEOUT_TIME = timedelta(seconds=20)
    """
    Время, после которого результат сопоставляется с другими,
    а затем удаляется из очереди.
    """

    current_time = datetime.now()

    results_by_time = sorted(results_by_process_id[0] + results_by_process_id[1],
                             key=attrgetter('finish_time'))

    for result in results_by_time:
        if current_time - result.finish_time < RESULT_TIMEOUT_TIME:
            break

        overdue_result = result
        opposite_worker_id = (overdue_result.worker_id + 1) % 2
        results1 = results_by_process_id[overdue_result.worker_id]
        results2 = results_by_process_id[opposite_worker_id]

        if overdue_result.is_paired:
            # этой пачке уже была подобрана пара и они были обработаны
            results1.popleft()
            continue

        logger.debug("Сопоставление данных с пачек")

        def is_relevant_result(r: TaskResult) -> bool:
            """
            Определяет находится ли текущий результат
            в eps-окрестности времени результата другой камеры.
            """
            nonlocal overdue_result
            diff_seconds = (overdue_result.finish_time - r.finish_time).total_seconds()
            diff_seconds = abs(diff_seconds)
            diff_time = timedelta(seconds=diff_seconds)
            return diff_time < MAX_CAMERAS_DIFF_TIME and not r.is_paired

        relevant_results1 = list(takewhile(is_relevant_result, results1))
        relevant_results2 = list(takewhile(is_relevant_result, results2))

        if len(relevant_results2) == 0:
            logger.warning("Для пачки не найдена пара (рассинхрон?)")

        results_with_codes1 = [
            result for result in relevant_results1 if len(result.qr_codes) != 0
        ]
        results_with_codes2 = [
            result for result in relevant_results2 if len(result.qr_codes) != 0
        ]

        if len(results_with_codes1) != 0 and len(results_with_codes2) != 0:
            logger.warning("QR- и штрихкоды обнаружены с обеих сторон пачки")

        if len(results_with_codes1) == 0 and len(results_with_codes2) == 0:
            logger.warning("QR- и штрихкодов нет с обеих сторон пачки")
            notify_that_no_packdata(domain_url)
        else:
            logger.debug("QR- и штрихкоды обнаружены")

            barcodes = []
            for codes in map(attrgetter('barcodes'), results_with_codes1):
                barcodes.extend(codes)
            for codes in map(attrgetter('barcodes'), results_with_codes2):
                barcodes.extend(codes)

            qr_codes = []
            for codes in map(attrgetter('qr_codes'), results_with_codes1):
                qr_codes.extend(codes)
            for codes in map(attrgetter('qr_codes'), results_with_codes2):
                qr_codes.extend(codes)

            if overdue_result.expected_codes_count != len(qr_codes):
                logger.warning(f"Ожидалось {overdue_result.expected_codes_count} кодов, "
                               f"но в сопоставленной группе их оказалось {len(qr_codes)}")

            notify_about_packdata(domain_url, barcodes=barcodes, qr_codes=qr_codes)

        for result in relevant_results1 + relevant_results2:
            result.is_paired = True
        results1.popleft()


def notify_about_packdata(
        domain_url: str,
        qr_codes: List[str],
        barcodes: List[str],
):
    """
    Оповещает сервер, что QR- и штрихкоды успешно считаны с пачки.
    Считанные данные также отправляются серверу.
    """

    success_pack_mapping = f'{domain_url}/api/v1_0/new_pack_after_pintset'
    REQUEST_TIMEOUT_SEC = 2

    for qr_code, barcode in zip(qr_codes, barcodes):
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


def notify_that_no_packdata(domain_url: str) -> None:
    """
    Оповещает сервер, что QR- и штрихкоды не были считаны с текущей пачки.
    """
    # TODO: ниже должен быть url для отправки запросов о пачке без QR- и штрихкодов
    empty_pack_mapping = f'{domain_url}/api/v1_0/!!!__TODO__FILLME__!!!'
    REQUEST_TIMEOUT_SEC = 2

    try:
        message = "Отправка извещения о пачке без данных на сервер"
        logger.debug(message)

        # REMOVAL
        # if get_work_mode(domain_url) == 'auto':
        #     pass
        # f = open ('line1time.txt', 'w')
        # f.write(str(time.time()+delay))
        # f.close()
        # er.snmp_set(er.OID['ALARM-1'],er.on)

        # TODO: ниже (вместо warning'а) должен быть запрос к серверу для случая,
        #  когда с обеих сторон пачки не обнаружено кодов
        logger.warning("Пачка без данных")

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
    except ConnectTimeout:
        logger.error("Аппликатор - нет Сети")
        return None


def get_pack_codes_count(domain_url: str, prev_value: int) -> Optional[int]:
    """
    Узнаёт от сервера, сколько QR-кодов ожидать на одной пачке
    """
    qr_count_mapping = f'{domain_url}/api/v1_0/current_batch'
    REQUEST_TIMEOUT_SEC = 2

    try:
        logger.debug("Получение данных об ожидаемом кол-ве QR-кодов")

        response = requests.get(qr_count_mapping, timeout=REQUEST_TIMEOUT_SEC)
        packs_in_block = int(response.json()['params']['multipacks_after_pintset'])
        return packs_in_block

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
        deque() for _ in processes_args
    ]
    expected_codes_count = 1
    iteration_count = 0

    def process_taskresult(event: TaskResult):
        msg = (f"Получены данные от процесса #{event.worker_id}: "
               f"QR={event.qr_codes} "
               f"BAR={event.barcodes} "
               f"время конца пачки='{event.finish_time}'")
        logger.debug(msg)
        event.is_paired = False
        event.expected_codes_count = expected_codes_count
        enqueue_new_result(
            results_by_process_id,
            event,
        )

    def process_taskerror(event: TaskError):
        msg = (f"В процессе #{event.worker_id} "
               f"произошла ошибка: {event.message}")
        logger.error(msg)

    def process_startscanning(event: StartScanning):
        msg = f"Процесс #{event.worker_id} начал сканирование"
        logger.info(msg)

    def process_endscanning(event: EndScanning):
        msg = f"Процесс #{event.worker_id} завершил работу"
        logger.info(msg)

        process = processes[event.worker_id]
        process.terminate()
        process.join()
        alive_count = sum(process.is_alive() for process in processes)
        if alive_count == 0:
            raise GeneratorExit("Все процессы завершили работу. Закрытие программы")

    event_processor = EventProcessor()
    event_processor.add_handler(process_taskresult)
    event_processor.add_handler(process_taskerror)
    event_processor.add_handler(process_startscanning)
    event_processor.add_handler(process_endscanning)

    def process_event(event: CamScannerEvent):
        event_processor.process_event(event)

    while True:
        try:
            if iteration_count == 0:
                expected_codes_count = get_pack_codes_count(domain_url, prev_value=expected_codes_count)
            iteration_count = (iteration_count + 1) % ITERATION_PER_REQUEST

            try:
                event: CamScannerEvent = queue.get(timeout=QUEUE_REQUEST_TIMEOUT_SEC)
            except Empty:
                continue
            event.receive_time = datetime.now()

            process_event(event)
            process_latest_results(results_by_process_id, domain_url)

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

    logger.add(sink=log_path, level=log_level, rotation='2 MB', compression='zip')

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
