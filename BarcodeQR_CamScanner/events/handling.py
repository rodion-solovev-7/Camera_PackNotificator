import abc
import inspect
from collections import deque
from inspect import signature
from typing import Callable, Optional, Iterable, Union

__all__ = ['BaseEvent', 'EventProcessor', 'EventsProcessingQueue', 'EventWorker']


class BaseEvent(metaclass=abc.ABCMeta):
    """Базовый класс для всех событий, обрабатываемых ``EventProcessor``'ом."""


class EventProcessor:
    """Обработчик событий, поступающих ему на вход."""

    def __init__(self):
        self.handlers = []

    def add_handler(self, handler: Callable):
        """
        Добавляет новую функцию-обработчик для событий.
        Тип события автоматически определяется из типа первого аргумента искомой функции.

        Params:
            handler: функция, тип первого аргумента которой должен быть унаследован от ``BaseEvent``

        Raises:
             ValueError: если в сигнатуре функции нет аргументов или класс первого
                         аргумента переданной функции не является наследником ``BaseEvent``
        """
        event_type = self._get_handler_eventtype(handler)
        if not issubclass(event_type, BaseEvent):
            message = f"{event_type} isn't one of ``BaseEvent``'s class inheritors"
            raise ValueError(message)
        self.handlers.append(handler)

    def process_event(self, event: BaseEvent) -> Iterable[BaseEvent]:
        """
        Обрабатывает событие поступившее на вход.
        К событию будут применены все добавленные подходящие ему обработчики
        (с учётом наследования).

        Params:
            event: событие, появление которого необходимо обработать
        """
        handler_types = map(self._get_handler_eventtype, self.handlers)
        for handler_type, handler in zip(handler_types, self.handlers):
            if not isinstance(event, handler_type):
                continue
            ret = handler(event)
            if isinstance(ret, BaseEvent):
                yield from (ret,)
                continue
            if ret is not None:
                yield from (event for event in ret if isinstance(event, BaseEvent))
                continue

    @staticmethod
    def _get_handler_eventtype(handler: Callable) -> type:
        """
        Возвращает тип события, которое обрабатывает данная функция-обработчик.

        Params:
            handler: функция, тип первого аргумента которой должен быть унаследован от ``BaseEvent``

        Returns:
            type: тип первого аргумента из сингнатуры, полученной функции

        Raises:
            ValueError: если в сигнатуре функции нет аргументов или класс первого
                        аргумента переданной функции не является наследником BaseEvent
        """
        sig = signature(handler)
        if len(sig.parameters) < 1:
            message = ("``handler`` должен содержать минимум 1 аргумент - "
                       "событие для обработки")
            raise ValueError(message)

        param, *_ = sig.parameters.values()
        event_type = param.annotation

        if not issubclass(event_type, BaseEvent):
            message = ("Первый аргумент функции ``handler`` должен быть "
                       "унаследован от ``BaseEvent``")
            raise ValueError(message)

        return event_type


class EventsProcessingQueue:
    """Очередь для событий, ожидающих своей обработки"""

    def __init__(self, event_processor: EventProcessor):
        self._queue = deque()
        self._processor = event_processor

    def __len__(self):
        return len(self._queue)

    def _process_event_and_add_new_events(self, event: BaseEvent):
        events = self._processor.process_event(event)
        for event in events:
            self.add_event(event)

    def process_latest(self):
        event = self.pop_latest()
        self._process_event_and_add_new_events(event)

    def add_event(self, event: BaseEvent):
        self._queue.append(event)

    def pop_latest(self) -> Optional[BaseEvent]:
        if len(self._queue) == 0:
            return None
        return self._queue.popleft()


class EventWorker:
    handlers = []
    start_events = []

    def __init__(self):
        self._event_processor = EventProcessor()
        self._event_processing_queue = EventsProcessingQueue(self._event_processor)

    def set_event_handlers(self):
        for handler in self.handlers:
            self._event_processor.add_handler(handler)

    def set_start_events(self):
        for event in self.start_events:
            self._event_processing_queue.add_event(event)

    def run_processing(self):
        while len(self._event_processing_queue) > 0:
            self._event_processing_queue.process_latest()
