"""
Детекторы объектов, основанные на различных методах.

Отвечают, есть ли объект в данный момент.
"""

from ._detectors import *

__all__ = [
    'BaseDetector',
    'NeuronetDetector',
    'BackgroundDetector',
    'SensorDetector',
]
