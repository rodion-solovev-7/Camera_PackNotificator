import multiprocessing as mp

from loguru import logger

from BarcodeQR_CamScanner.di_containers import ApplicationContainer
from BarcodeQR_CamScanner.networking.workers import AsyncMainWorker
from BarcodeQR_CamScanner.scanning.workers import CameraScannerProcess


def main():
    """
    Запускает сканирование согласно конфигурации из ``config.yaml``-файла.
    """
    di_container = ApplicationContainer()
    di_container.config.from_yaml('config.yaml')

    log_path = di_container.networking.log_path()
    log_level = di_container.networking.log_level()
    logger.add(sink=log_path, level=log_level, rotation='2 MB', compression='zip')

    queue = mp.Queue()
    api = di_container.networking.NetworkApi()
    consolidator = di_container.networking.CodesConsolidator()
    async_worker = AsyncMainWorker(api=api, queue=queue, consolidator=consolidator)
    camera_worker = CameraScannerProcess(queue, 1)
    try:
        camera_worker.start()
        async_worker.run_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
