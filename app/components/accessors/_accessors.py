import abc
import asyncio
from threading import Lock

from ..network_sources import Backend


class BaseAccessor(metaclass=abc.ABCMeta):
    """
    Предоставляет доступ к актуальным данным
    (в зависимости от них варьируется поведение программы)
    """

    # TODO: подумать над более оптимальным доступом к данным для различных компонентов
    @abc.abstractmethod
    async def update(self) -> None:
        """Регулярно обновляет данные"""

    @abc.abstractmethod
    def get_expected_codes_count(self) -> int:
        """
        Возвращает ожидаемое кол-во кодов
        """

    @abc.abstractmethod
    def get_current_work_mode(self) -> str:
        """
        Возвращает текущий режим работы
        """


class BackendAccessor(BaseAccessor):
    """
    Предоставляет данные к актуальным данным бэкенда
    """

    def __init__(
            self,
            backend: Backend,
            *,
            init_work_mode: str = 'auto',
            init_codes_count: int = 2,
    ):
        self._backend = backend

        self._work_mode = init_work_mode
        self._codes_count = init_codes_count

        # TODO: переработать механизм обновления данных для избавления от блокировок
        self._lock = Lock()

    async def update(self) -> None:
        """
        Периодически обновляет данные, лежащие в экземпляре класса.
        """
        while True:

            mode = await self._backend.get_mode()
            if mode is not None:
                with self._lock:
                    self._work_mode = mode

            codes_count = await self._backend.get_multipacks_after_pintset()
            if codes_count is not None:
                with self._lock:
                    self._codes_count = codes_count

            await asyncio.sleep(10)

    def get_expected_codes_count(self) -> int:
        """
        Возвращает ожидаемое кол-во кодов
        """
        with self._lock:
            return self._codes_count

    def get_current_work_mode(self) -> str:
        """
        Возвращает текущий режим работы
        """
        with self._lock:
            return self._work_mode


class ImmutableAccessor(BaseAccessor):
    """
    Симулирует предоставление доступа к данным бэкенда
    """

    def __init__(
            self,
            *,
            init_work_mode: str = 'auto',
            init_codes_count: int = 2,
    ):
        self._work_mode = init_work_mode
        self._codes_count = init_codes_count

    async def update(self) -> None:
        """НИЧЕГО НЕ ДЕЛАЕТ - ДАННЫЕ ОСТАЮТСЯ НАВСЕГДА"""
        return

    def get_expected_codes_count(self) -> int:
        """
        Возвращает ожидаемое кол-во кодов (всегда одно и тоже)
        """
        return self._codes_count

    def get_current_work_mode(self) -> str:
        """
        Возвращает текущий режим работы (всегда один и тот же)
        """
        return self._work_mode
