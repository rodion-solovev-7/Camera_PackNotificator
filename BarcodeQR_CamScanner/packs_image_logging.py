import abc
import os
from datetime import datetime

import cv2
import numpy as np


class BaseImagesLogger(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def add(self, image: np.ndarray) -> None:
        pass

    @abc.abstractmethod
    def save(self) -> None:
        pass

    @abc.abstractmethod
    def clear(self) -> None:
        pass


class FakeImagesSaver(BaseImagesLogger):
    def add(self, image: np.ndarray) -> None:
        pass

    def save(self) -> None:
        pass

    def clear(self) -> None:
        pass


class ImagesSaver(BaseImagesLogger):
    def __init__(self, path: str, buffer_size: int = 50):
        self._path = path
        self._BUFFER_SIZE = buffer_size
        self._buffer = list()

    def add(self, image: np.ndarray) -> None:
        if len(self._buffer) < self._BUFFER_SIZE:
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
