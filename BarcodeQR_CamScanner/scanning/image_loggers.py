"""
Логгеры для тяжёлый данных, возникающий при обработке видео.

Сохраняют тяжёлые трудно логгируемые данные
(например, картинки, видео, битовые маски изображений) на диск.

Данные используются для последующего анализа корректности работы
или выявления ошибочных ситуаций.
"""
import abc
import os
from datetime import datetime

import cv2
import numpy as np

from .image_utils import get_resized


class BaseImagesLogger(metaclass=abc.ABCMeta):
    """
    Базовый класс логгирования изображений.
    Занимается сохранением сомнительных случаев
    с видео на диск для дальнейшего анализа.
    """
    @abc.abstractmethod
    def add(self, image: np.ndarray) -> None:
        """
        Добавляет изображение в буффер лога
        """

    @abc.abstractmethod
    def save(self) -> None:
        """
        Сохраняет изображения из буффера
        """

    @abc.abstractmethod
    def clear(self) -> None:
        """
        Удаляет изображения из буффера
        """


class FakeImagesSaver(BaseImagesLogger):
    """
    Логгер изображений, который ничего никогда не логгирует.
    Заглушка для обработки видео без сохранения изображений.
    """
    def add(self, image: np.ndarray) -> None:
        pass

    def save(self) -> None:
        pass

    def clear(self) -> None:
        pass


class ImagesBufferedSaver(BaseImagesLogger):
    """
    Логгер, сохраняющий изображения с определёнными именами в заданную папку.
    Количество изображений для каждой пачки лимитировано размером буффера.

    Использовать с осторожностью! Не следит за переполнением диска!
    """
    def __init__(self, path: str, *, buff_size: int = 50, sizer: float = 1.0):
        self._path = path
        self._BUFFER_SIZE = buff_size
        self._buffer = list()
        self._SIZER = sizer

    def add(self, image: np.ndarray) -> None:
        if len(self._buffer) < self._BUFFER_SIZE:
            if self._SIZER is not None:
                image = get_resized(image, sizer=self._SIZER)
            self._buffer.append(image)

    def save(self) -> None:
        foldername = datetime.now().strftime('%y-%m-%d_%H-%M-%S')
        folderpath = os.path.join(self._path, foldername)
        os.makedirs(folderpath, exist_ok=True)
        for i, image in enumerate(self._buffer, 1):
            filepath = os.path.join(folderpath, f'{i:03}.png')
            cv2.imwrite(filepath, image)

    def clear(self) -> None:
        self._buffer.clear()
