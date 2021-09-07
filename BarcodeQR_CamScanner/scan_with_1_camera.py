import os

from loguru import logger

from .camera_main_workers import SingleCameraWorker
from .env_loading import setup_logger, collect_scanners_args


def run():
    """
    Готовит список аргументов, логер и запускает выполнение
    событийного цикла по обработке событий от сканера
    """
    domain_url = os.getenv('DOMAIN_URL', 'http://localhost')
    setup_logger()

    processes_args = collect_scanners_args()[:1]

    try:
        runner = SingleCameraWorker(processes_args, domain_url)
        runner.run_processing()
    except KeyboardInterrupt as e:
        logger.info(f"Выполнение прервано {e}")
    except BaseException as e:
        logger.critical("Падение с критической ошибкой")
        logger.opt(exception=e)
        raise e
