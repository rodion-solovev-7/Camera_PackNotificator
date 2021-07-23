from inspect import signature
from typing import Type, Callable


class BaseEvent:
    """Базовый класс для всех событий, обрабатываемых ``EventProcessor``'ом."""


class EventProcessor:
    """Обработчик событий, поступающих ему на вход."""
    def __init__(self, ):
        self.handlers = []

    def add_handler(self, handler: Callable[[Type[BaseEvent]], None]):
        """
        Добавляет новую функцию-обработчик для событий.
        Тип события автоматически определяется из типа первого аргумента искомой функции.
        """
        event_type = self._get_handler_eventtype(handler)
        if not issubclass(event_type, BaseEvent):
            message = f"{event_type} isn't one of ``BaseEvent``'s class inheritors"
            raise ValueError(message)
        self.handlers.append(handler)

    def process_event(self, event: Type[BaseEvent]) -> None:
        """
        Обрабатывает событие поступившее на вход.
        К событию будут применены все добавленные подходящие ему обработчики
        (с учётом наследования).
        """
        handler_types = map(self._get_handler_eventtype, self.handlers)
        for handler_type, handler in zip(handler_types, self.handlers):
            if isinstance(event, handler_type):
                handler(event)

    @staticmethod
    def _get_handler_eventtype(
            handler: Callable[[Type[BaseEvent]], None],
    ) -> type:
        sig = signature(handler)
        if len(sig.parameters) < 1:
            message = ("BaseEvent ``handler`` must contains at least 1 argument: "
                       "event for processing")
            raise ValueError(message)

        param, *_ = sig.parameters.values()
        event_type = param.annotation

        if not issubclass(event_type, BaseEvent):
            message = ("First argument of ``handler`` should be "
                       "one of ``BaseEvent`` subclasses")
            raise ValueError(message)

        return event_type
