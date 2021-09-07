import os

from loguru import logger

from .camera_main_workers import SingleCameraWorker
from .env_loading import setup_logger, collect_scanners_args
from .packs_validation import IllegibleCameraProcessingQueue, InstantCameraProcessingQueue


def run():
    """
    Готовит список аргументов, логер и запускает выполнение
    событийного цикла по обработке событий от сканера
    """
    domain_url = os.getenv('DOMAIN_URL', 'http://localhost')
    fill_missing = os.getenv('FILL_MISSING_PACK_DATA', '0')
    fill_missing = int(fill_missing) != 0

    if fill_missing:
        pack_processing_queue = IllegibleCameraProcessingQueue()
    else:
        pack_processing_queue = InstantCameraProcessingQueue()

    setup_logger()

    processes_args = collect_scanners_args()[:1]

    try:
        runner = SingleCameraWorker(processes_args, domain_url, pack_processing_queue)
        runner.run_processing()
    except KeyboardInterrupt as e:
        logger.info(f"Выполнение прервано {e}")
    except BaseException as e:
        logger.critical("Падение с критической ошибкой")
        logger.opt(exception=e)
        raise e
