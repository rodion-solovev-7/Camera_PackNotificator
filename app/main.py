"""
Файл с кодом для запуска сканирования.
Предполагает, что конфиг существует и содержит корректные данные (пути к видео, компоненты и т.п).
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

from loguru import logger

from app.di_containers import Application
from app.processing import process_video


def create_yaml_config_if_no_exists():
    """
    Копирует .yaml конфиг с настройками по умолчанию,
    если не находит других конфигов.
    """
    if not (Path('.') / f"config.yaml").is_file():
        print("Not found existing config.yaml. Creating new one")
        from shutil import copyfile
        copyfile(Path(__file__).parent.parent / 'sample_config.yaml', './config.yaml')


def get_complete_di_container() -> Application:
    """
    Инициализирует DataInjection-контейнер из конфига в рабочей директории программы.
    Возвращает инициализированный контейнер.

    Returns:
        Application
    """
    container = Application()
    container.config.from_yaml('config.yaml')
    return container


def setup_logger(file: str, log_format: str, level: str = 'DEBUG') -> None:
    """
    Настраивает логгирование с ротацией и автоматическим сжатием в zip.

    Returns:
        None
    """
    logger.remove()
    logger.add(sink=sys.stdout, format=log_format)
    logger.add(sink=file, format=log_format, level=level, rotation='1 day', compression='zip')


def get_running_parallel_eventloop() -> asyncio.AbstractEventLoop:
    """
    Запускает бесконечный eventloop в параллельном потоке исполнения.

    ! Это необходимое зло чтобы не создавать по потоку на каждый сетевой запрос !

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


def main() -> None:
    """
    Запускает обработку видео с извещение бэкенда и логгированием происходящих событий.
    """
    create_yaml_config_if_no_exists()

    container = get_complete_di_container()
    setup_logger(
        file=container.get_log_path(),
        log_format=container.get_log_format(),
        level=container.get_log_level(),
    )
    logger.info(f"local time is {datetime.now()!s}")

    detector = container.detection.Detector()
    accessor = container.accessing.Accessor()

    eventloop = get_running_parallel_eventloop()

    # TODO: подумать над более оптимальным доступом к данным для различных компонентов
    #  (не таким)
    asyncio.run_coroutine_threadsafe(detector.update(), eventloop)
    asyncio.run_coroutine_threadsafe(accessor.update(), eventloop)

    logger.info("Программа запущена")
    try:
        process_video(
            video_path=container.get_video_path(),
            detector=detector,
            accessor=accessor,
            validator=container.validation.Validator(),
            notifier=container.notification.Notifier(),
            eventloop=eventloop,
            video_sizer=container.get_video_sizer(),
        )
    except KeyboardInterrupt:
        logger.info("Программа была остановлена пользователем (Ctrl+C)")
    except BaseException as e:
        logger.opt(exception=e).critical("Программа была неожиданно завершена из-за ошибки")
    logger.info("Программа завершена")


if __name__ == '__main__':
    main()
