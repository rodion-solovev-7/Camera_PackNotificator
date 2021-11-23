"""
Файл с кодом для запуска сканирования.
Предполагает, что конфиг существует и содержит корректные данные (пути к видео, компоненты и т.п).
"""
import asyncio
import sys

from loguru import logger

from app.di_containers import ApplicationContainer
from app.processing import process_video


def create_yaml_config_if_no_configs():
    """
    Копирует .yaml конфиг с настройками по умолчанию,
    если не находит других конфигов.
    """
    config_extension = [
        'yaml',
        # TODO: добавить поддержку разных форматов конфигов
        # 'env',
        # 'xml',
        # 'json',
    ]

    from pathlib import Path
    workdir = Path('.')
    for ext in config_extension:
        if (workdir / f"config.{ext}").is_file():
            break
    else:
        print("Not found existing config.yaml. Created new one config.yaml")
        from shutil import copyfile
        copyfile(Path(__file__).parent.parent / 'sample_config.yaml', './config.yaml')


def get_complete_di_container() -> ApplicationContainer:
    """
    Инициализирует DataInjection-контейнер из конфига в рабочей директории программы.
    Возвращает инициализированный контейнер.

    Returns:
        ApplicationContainer
    """
    container = ApplicationContainer()
    container.config.from_yaml('config.yaml')
    return container


def setup_logger(file: str, format_: str, level: str = 'DEBUG') -> None:
    """
    Настраивает логгирование с ротацией и автоматическим сжатием в zip.

    Returns:
        None
    """
    logger.remove()
    logger.add(sink=sys.stdout, format=format_)
    logger.add(sink=file, format=format_, level=level, rotation='1 day', compression='zip')


def get_running_parallel_eventloop() -> asyncio.AbstractEventLoop:
    """
    Запускает бесконечный eventloop в параллельном потоке исполнения.

    !Э то необходимое зло чтобы не создавать по потоку на каждый сетевой запрос !

    Отправлять задачи такому eventloop'у можно так:
        >>> async def coroutine(arg1, arg2):
        >>>     "здесь выполняем что нам нужно"
        >>>
        >>> asyncio.run_coroutine_threadsafe(coroutine(12, 34), asyncio.get_event_loop())
    """

    def run_eventloop_forever(loop: asyncio.AbstractEventLoop):
        """
        Вызывает блокирующий loop.run_forever() асинхронного цикла.
        """
        loop.run_forever()

    eventloop = asyncio.new_event_loop()
    # делает переданный eventloop стандартным для потока, в котором исполняется
    asyncio.set_event_loop(eventloop)

    # daemon=True гарантирует нам, что при завершении главного потока,
    # дочерний умрёт вместе с ним (даже если он в этот момент что-то выполнял!)
    from threading import Thread
    t = Thread(target=run_eventloop_forever, args=(eventloop,), daemon=True)
    t.start()

    return eventloop


def run() -> None:
    """
    Запускает обработку видео с извещение бэкенда и логгированием происходящих событий.

    Returns:
        None
    """
    create_yaml_config_if_no_configs()

    container = get_complete_di_container()
    setup_logger(
        file=container.get_log_path(),
        format_=container.get_log_format(),
        level=container.get_log_level(),
    )

    logger.info("Программа запущена")
    try:
        process_video(
            video_path=container.get_video_path(),
            detector=container.detection.Detector(),
            tracker=container.tracking.Tracker(),
            api=container.network.ApiWrapper(),
            eventloop=get_running_parallel_eventloop(),
            video_sizer=container.get_video_sizer(),
        )
    except KeyboardInterrupt:
        logger.info("Программа была остановлена пользователем (Ctrl+C)")
    except BaseException as e:
        logger.critical("Программа была неожиданно завершена из-за ошибки")
        logger.opt(exception=True).critical(e)
    logger.info("Программа завершена")


if __name__ == '__main__':
    run()
