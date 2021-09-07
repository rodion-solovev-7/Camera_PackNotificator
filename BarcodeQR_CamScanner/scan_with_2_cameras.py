"""
Здесь происходит запуск и управление 2 процессами, которые читают коды с камер,
получение от них данных, их синхронизация между собой и отправка запросов с финальными данными.
"""
import os

from loguru import logger

from .camera_main_workers import DuoCamerasWorker
from .env_loading import setup_logger, collect_scanners_args


def run():
    """
    Готовит список аргументов, логер и запускает выполнение
    событийного цикла по обработке событий процессов-сканеров.
    """
    domain_url = os.getenv('DOMAIN_URL', 'http://localhost')
    setup_logger()

    # аргументы для worker_task (кроме queue и worker_id) для запуска в разных процессах
    processes_args = collect_scanners_args()[:2]

    try:
        runner = DuoCamerasWorker(processes_args, domain_url)
        runner.run_processing()
    except BaseException as e:
        logger.critical("Падение с критической ошибкой")
        logger.opt(exception=e)
        raise e
