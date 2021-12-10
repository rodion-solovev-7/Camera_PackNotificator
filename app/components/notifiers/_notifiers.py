import abc
import asyncio
import time

from loguru import logger

from ..network_sources import Shutter, Backend


class BaseNotifier(metaclass=abc.ABCMeta):
    """
    Базовый класс для всех сетевых взаимодействий с чем-либо извне.
    """

    @abc.abstractmethod
    async def notify_about_good_pack(self, pack_data: dict) -> None:
        """Уведомить, что прошла пачка с указанными кодами"""

    @abc.abstractmethod
    async def notify_about_bad_pack(self, pack_data: dict) -> None:
        """Уведомить, что прошла некорректная пачка"""


class AbstractBackendNotifier(BaseNotifier, metaclass=abc.ABCMeta):
    """
    Обёртка для отправки сообщений бэкенду.
    """

    def __init__(self, backend: Backend):
        self._backend = backend

    async def _send_pack_data(self, pack_data: dict) -> None:
        """
        Отправляет корректные коды бэкенду
        """
        logger.info(f"Отправка бэкенду кодов: {pack_data}")
        for qr, bar in zip(pack_data['QRCODE'], pack_data['EAN13']):
            await self._backend.send_codepair(qr, bar)


class EmptyLoggingNotifier(BaseNotifier):
    """
    Заглушка, которая не посылает никаких запросов, но всё логгирует.
    """

    async def notify_about_good_pack(self, pack_data: dict) -> None:
        """Заглушка для логирования"""
        logger.debug(f"Извещение о корректной пачке: {pack_data}")

    async def notify_about_bad_pack(self, pack_data: dict) -> None:
        """Заглушка для логирования"""
        logger.debug(f"Извещение о некорректной пачке: {pack_data}")


class AbstractShutterNotifier(BaseNotifier, metaclass=abc.ABCMeta):
    """
    Обёртка с функционалом сброса пачек заслонкой
    """

    _WAIT_BEFORE_SEC: float
    _WAIT_OPEN_SEC: float

    def __init__(
            self,
            *,
            shutter: Shutter,
            wait_before_sec: float = 8,
            wait_open_sec: float = 25,
    ):
        self._shutter = shutter

        self._WAIT_BEFORE_SEC = wait_before_sec
        self._WAIT_OPEN_SEC = wait_open_sec

        self._is_shutter_open = False
        self._shutter_close_time = time.monotonic()

    async def _drop_pack(self) -> None:
        """
        Асинхронно ждёт, открывает сброс пачек и через некоторое время закрывает его.
        Если ещё до закрытия заслонки на сброс была отправлена
        новая группа пачек, то заслонка остаётся в открытом состоянии.
        """
        awake_time = self._WAIT_BEFORE_SEC + self._WAIT_OPEN_SEC
        self._shutter_close_time = time.monotonic() + awake_time

        await asyncio.sleep(self._WAIT_BEFORE_SEC)
        if not self._is_shutter_open:
            logger.info("Открыта заслонка - начало сброса пачек")
            self._is_shutter_open = True
            await self._shutter.open()

        await asyncio.sleep(self._WAIT_OPEN_SEC)
        if self._is_shutter_open and time.monotonic() > self._shutter_close_time - 1e-3:
            self._is_shutter_open = False
            logger.info("Закрыта заслонка - окончание сброса пачек")
            await self._shutter.close()


class BackendNotifier(AbstractBackendNotifier):
    """
    Версия API-обёртки для случаев, где сам бэкенд занимается сбросом плохих пачек.
    """

    async def notify_about_good_pack(self, pack_data: dict) -> None:
        """
        Отправляет корректные коды бэкенду
        """
        await self._send_pack_data(pack_data)

    async def notify_about_bad_pack(self, pack_data: dict) -> None:
        """
        Отправляет некорректные коды бэкенду в надежде, что он их сбросит сам
        """
        await self._send_pack_data(pack_data)


class BackendNotifierWithShutter(AbstractBackendNotifier, AbstractShutterNotifier):
    """
    Версия API, которая ставит сбрасывает некорректные пачки заслонкой.
    Корректные отправляются бэкенду.
    """

    def __init__(
            self,
            *,
            backend: Backend,
            shutter: Shutter,
            use_shutter_for_bad_packs: bool = True,
            use_backend_for_bad_packs: bool = False,
            shutter_wait_before_sec: float = 8,
            shutter_wait_open_sec: float = 25,
    ):
        AbstractBackendNotifier.__init__(self, backend=backend)
        AbstractShutterNotifier.__init__(
            self,
            shutter=shutter,
            wait_before_sec=shutter_wait_before_sec,
            wait_open_sec=shutter_wait_open_sec,
        )

        self._use_shutter_for_bad_packs = use_shutter_for_bad_packs
        self._use_backend_for_bad_packs = use_backend_for_bad_packs

    async def notify_about_good_pack(self, pack_data: dict) -> None:
        """
        Отправляет корректные коды бэкенду
        """
        await self._send_pack_data(pack_data)

    async def notify_about_bad_pack(self, pack_data: dict) -> None:
        """
        Сбрасывает пачки заслонкой, не извещая о них сервер.
        """
        if self._use_backend_for_bad_packs:
            await self._send_pack_data(pack_data)
        if self._use_shutter_for_bad_packs:
            await self._drop_pack()
