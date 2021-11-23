"""
Обёртки для сетевых взаимодействий.
Через Api-классы, объявленные здесь, должно проходить всё сетевое взаимодействие с источниками извне.

Например, здесь должны http или https запросы к бэкенду, запросы к БД или snmp-запросы к оборудованию и прочие.
"""

import abc

import aiohttp
from loguru import logger


class BaseApi(metaclass=abc.ABCMeta):
    """
    Базовый класс для всех сетевых взаимодействий с чем-либо извне.
    """

    @abc.abstractmethod
    async def notify_object_spawned(self, *, track_id: int, object_id: int = None) -> None:
        """
        Извещает, что объект попал на конвейер с одного из путей.

        Args:
            track_id: номер пути, с которого пришла пачка
            object_id: идентификатор пачки (может быть пустым)

        Returns:
            None
        """

    @abc.abstractmethod
    async def notify_object_delivered(self, *, track_id: int, object_id: int = None) -> None:
        """
        Извещает, что объект успешно прошёл дальше.

        Args:
            track_id: номер пути, с которого пришла пачка
            object_id: идентификатор пачки (может быть пустым)

        Returns:
            None
        """

    @abc.abstractmethod
    async def notify_object_confiscated(self, *, track_id: int, object_id: int = None) -> None:
        """
        Извещает, что объект была изъят.

        Args:
            track_id: номер пути, с которого пришла пачка
            object_id: идентификатор пачки (может быть пустым)

        Returns:
            None
        """


class EmptyLoggingApi(BaseApi):
    """
    Заглушка, которая не посылает никаких запросов, но всё логгирует.
    """

    async def notify_object_spawned(self, *, track_id: int, object_id: int = None) -> None:
        """Метод-заглушка для логирования"""
        message = f"Объект попал на конвейер ({track_id = } {object_id = })"
        logger.info(message)

    async def notify_object_delivered(self, *, track_id: int, object_id: int = None) -> None:
        """Метод-заглушка для логирования"""
        message = f"Объект успешно прошёл ({track_id = } {object_id = })"
        logger.info(message)

    async def notify_object_confiscated(self, *, track_id: int, object_id: int = None) -> None:
        """Метод-заглушка для логирования"""
        message = f"Объект был изъят ({track_id = } {object_id = })"
        logger.info(message)


class ApiWithoutSpawnAndConfiscation(EmptyLoggingApi):
    """
    Обёртка, извещающая бэкенд, когда объект доходит до конца пути.
    Изъятие и появление объекта логируются без отправки бэкенду.
    """

    def __init__(self, *, domain_url: str):
        self.domain_url = domain_url.rstrip('/')
        # noinspection SpellCheckingInspection
        self.delivered_route = 'api/v1_0/pintset_finish'

    async def notify_object_delivered(self, *, track_id: int, object_id: int = None) -> None:
        """
        Извещает бэкенд о том, что объект, пришедший от определённого источника, достигл цели.
        """
        await super().notify_object_delivered(track_id=track_id, object_id=object_id)

        logger.info("Извещение бэкенда о паллете, зашедшей в обмотчик")

        async with aiohttp.ClientSession() as session:
            try:
                url = f'{self.domain_url}/{self.delivered_route}'
                async with session.put(url) as resp:
                    logger.info(f"{resp.status = } "
                                f"({track_id = } {object_id = })")
                    logger.info(f"{await resp.json()} "
                                f"({track_id = } {object_id = })")
            except Exception as e:
                logger.error("Произошла ошибка во время отправки извещения бэкенду"
                             f"({track_id = } {object_id = })")
                logger.opt(exception=e)
