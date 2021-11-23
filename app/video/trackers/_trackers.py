"""
Трекеры объектов на изображении.

Отвечают за связывание объектов с одного кадра с объектами с другого.
"""
import abc
from collections import OrderedDict

import numpy as np
from scipy.spatial import distance as dist


class BasePackTracker(metaclass=abc.ABCMeta):
    """
    Базовый класс для всех трекеров.
    """
    def update(self, rectangles: list[tuple[int, int, int, int]]) -> dict[int, tuple[int, int]]:
        """
        Обновляет позиции объекта на изображении.
        """


class CentroidObjectTracker:
    """
    Трекер объектов по их центральным точкам.
    """

    def __init__(self, *, max_disappeared: int = 20, max_object_id: int = 2 ** 64 - 1):
        # initialize the next unique object ID along with two ordered
        # dictionaries used to keep track of mapping a given object
        # ID to its centroid and number of consecutive frames it has
        # been marked as "disappeared", respectively
        self.objects = OrderedDict()
        self.disappeared = OrderedDict()
        self.next_object_id = 0
        self.max_object_id = max_object_id

        # store the number of maximum consecutive frames a given
        # object is allowed to be marked as "disappeared" until we
        # need to unregister the object from tracking
        self.max_disappeared = max_disappeared

    def register(self, centroid):
        """
        Добавляет новый объект в список отслеживаемых и выдаёт ему собственный id.
        """
        self.objects[self.next_object_id] = centroid
        self.disappeared[self.next_object_id] = 0
        self.next_object_id = (self.next_object_id + 1) % 10_000

    def unregister(self, object_id: int):
        """
        Удаляет объект, его позицию и id из отслеживаемых.
        """
        self.objects.pop(object_id)
        self.disappeared.pop(object_id)

    def update(
            self,
            rectangles: list[tuple[int, int, int, int]],
    ) -> dict[int, tuple[int, int]]:
        """
        Обновляет позиции объектов: добавляет новые и пересчитывает позицию для старых.
        """
        # check to see if the list of input bounding box rectangles
        # is empty

        new2unregister = []
        if len(rectangles) == 0:
            # loop over any existing tracked objects and mark them
            # as disappeared
            for object_id in self.disappeared.keys():
                self.disappeared[object_id] += 1

                # if we have reached a maximum number of consecutive
                # frames where a given object has been marked as
                # missing, unregister it
                if self.disappeared[object_id] > self.max_disappeared:
                    new2unregister.append(object_id)

            for object_id in new2unregister:
                self.unregister(object_id)

            # return early as there are no centroids or tracking info
            # to update
            return self.objects

        input_centroids = np.zeros((len(rectangles), 2), dtype=np.int)

        # loop over the bounding box rectangles
        for i, (beg_x, beg_y, w, h) in enumerate(rectangles):
            # use the bounding box coordinates to derive the centroid
            # TODO: убрать сопоставление по y-координате
            center_x = beg_x + w // 2
            center_y = beg_y + h // 2
            input_centroids[i] = center_x, center_y

        if len(self.objects) == 0:
            for i in range(len(input_centroids)):
                self.register(input_centroids[i])
        else:
            # grab the set of object IDs and corresponding centroids
            object_ids = list(self.objects.keys())
            object_centroids = list(self.objects.values())

            # compute the distance between each pair of object
            # centroids and input centroids, respectively -- our
            # goal will be to match an input centroid to an existing
            # object centroid
            D = dist.cdist(np.array(object_centroids), input_centroids)

            # in order to perform this matching we must (1) find the
            # smallest value in each row and then (2) sort the row
            # indexes based on their minimum values so that the row
            # with the smallest value is at the *front* of the index
            # list
            rows = D.min(axis=1).argsort()

            # next, we perform a similar process on the columns by
            # finding the smallest value in each column and then
            # sorting using the previously computed row index list
            cols = D.argmin(axis=1)[rows]
            used_rows = set()
            used_cols = set()

            # loop over the combination of the (row, column) index
            # tuples
            for row, col in zip(rows, cols):
                # if we have already examined either the row or
                # column value before, ignore it
                # val
                if row in used_rows or col in used_cols:
                    continue

                # otherwise, grab the object ID for the current row,
                # set its new centroid, and reset the disappeared
                # counter
                object_id = object_ids[row]
                self.objects[object_id] = input_centroids[col]
                self.disappeared[object_id] = 0

                # indicate that we have examined each of the row and
                # column indexes, respectively
                used_rows.add(row)
                used_cols.add(col)
            unused_rows = set(range(D.shape[0])).difference(used_rows)
            unused_cols = set(range(D.shape[1])).difference(used_cols)
            if D.shape[0] >= D.shape[1]:
                # loop over the unused row indexes
                for row in unused_rows:
                    # grab the object ID for the corresponding row
                    # index and increment the disappeared counter
                    object_id = object_ids[row]
                    self.disappeared[object_id] += 1

                    # check to see if the number of consecutive
                    # frames the object has been marked "disappeared"
                    # for warrants unregistering the object
                    if self.disappeared[object_id] > self.max_disappeared:
                        self.unregister(object_id)
            else:
                for col in unused_cols:
                    self.register(input_centroids[col])

        return self.objects
