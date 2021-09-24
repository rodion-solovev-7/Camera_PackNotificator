import abc
import asyncio
import multiprocessing as mp
from queue import Empty

from loguru import logger

from .api_wrappers import BaseNetworkingApi
from .codes_consolidation import BaseResultConsolidationQueue
from ..models import ValidatedPack, PackGoodCodes, PackBadCodes, CameraPackResult


class BaseAsyncWorker(metaclass=abc.ABCMeta):
    def __init__(self):
        self._loop = asyncio.get_event_loop()
        self._setup_eventloop()

    @abc.abstractmethod
    def _setup_eventloop(self) -> None:
        """Устанавливает стартовые задачи во внутренний ``eventloop``"""

    def run_forever(self) -> None:
        """Запускает внутренний ``eventloop`` на бесконечное выполнение"""
        self._loop.run_forever()


class AsyncMainWorker(BaseAsyncWorker):
    """
    Асинхронный обработчик для событий с одной камеры.
    Читает и обрабатывает события, отправленные через мультипроцессную очередь.
    Регулярно обновляет режим работы и ожидаемое количество кодов.
    """
    _api: BaseNetworkingApi
    _queue: mp.Queue
    _workmode: str
    _expected_codes_count: int

    def __init__(
            self,
            *,
            api: BaseNetworkingApi,
            queue: mp.Queue,
            consolidator: BaseResultConsolidationQueue,
            expected_codes_count: int = 2,
            workmode: str = 'auto',
    ):
        super().__init__()
        self._api = api
        self._queue = queue
        self._consolidator = consolidator
        self._expected_codes_count = expected_codes_count
        self._workmode = workmode

    def _setup_eventloop(self) -> None:
        """
        Установка задач на бесконечную проверку и обработку событий,
        поступающих из мультипроцессной очереди, а также регулярного
        обновления ожидаемого кол-ва кодов и режима работы.
        """
        self._loop.create_task(self._endless_keep_actual_state())
        self._loop.create_task(self._endless_handle_queue_events())

    async def _endless_keep_actual_state(self) -> None:
        """
        Бесконечно асинхронно запрашивает актуальные
        ожидаемое кол-во кодов и режим работы.
        """
        while True:
            await self._update_codes_count()
            await self._update_workmode()
            await asyncio.sleep(15)

    async def _endless_handle_queue_events(self) -> None:
        """
        Бесконечно асинхронно обрабатывает события из мультипроцессной очереди.
        """
        while True:
            try:
                raw_pack: CameraPackResult = self._queue.get_nowait()
                logger.debug(f"Получены данные от процесса-камеры: {raw_pack}")
                raw_pack.expected_codes_count = self._expected_codes_count
                raw_pack.workmode = self._workmode
                self._consolidator.enqueue(raw_pack)
            except Empty:
                pass
            validated = self._consolidator.get_processed_latest()
            for pack in validated:
                await self._send_codes(pack)
            await asyncio.sleep(0.05)

    async def _update_workmode(self) -> None:
        """
        Запрашивает режим работы с сервера и сохраняет его.
        Если запрос не удался, оставляет предыдущий режим работы.
        """
        new_workmode = await self._api.get_workmode()
        if new_workmode is not None:
            logger.info('Режим работы обновлён: '
                        f'{self._workmode!r}->{new_workmode!r}')
            self._workmode = new_workmode

    async def _update_codes_count(self) -> None:
        """
        Запрашивает кол-во кодов с сервера и сохраняет его.
        Если запрос не удался, оставляет предыдущее ожидаемое кол-во кодов.
        """
        new_codes_count = await self._api.get_expected_codes_count()
        if new_codes_count is not None:
            logger.info('Кол-во кодов обновлено: '
                        f'{new_codes_count!r}->{self._expected_codes_count!r}')
            self._expected_codes_count = new_codes_count

    async def _send_codes(self, pack: ValidatedPack) -> None:
        """
        Извещает о результате валидации пачки
        """
        if isinstance(pack, PackGoodCodes):
            await self._api.notify_about_good_pack(pack)
        elif isinstance(pack, PackBadCodes):
            await self._api.notify_about_bad_pack(pack)
        else:
            logger.error(f"Неподдерживаемый результат обработки: {pack}")
