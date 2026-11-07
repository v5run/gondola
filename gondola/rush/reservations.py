"""Shared minute-level resource kernel for Rush and order admission.

One slot per station; all cooking stations share cooks; finishing/packing is
separate. Callers supply observed durations/dependencies, never future truth.
"""
from __future__ import annotations


class Reservations:
    def __init__(self, now: int, cooks: int, stations: list[str], blocked: dict[str, int], horizon: int):
        self.now, self.cooks, self.horizon = now, cooks, horizon
        self.occupancy = {s: [0] * (horizon + 1) for s in stations}
        self.labour = [0] * (horizon + 1)
        self.rows: list[dict] = []
        for s, until in blocked.items():
            for minute in range(now, min(until, horizon)):
                self.occupancy[s][minute] = 1

    def find_slot(self, station: str, earliest: int, duration: int) -> int:
        for start in range(max(self.now, earliest), self.horizon - duration + 1):
            if all(self.occupancy[station][m] < 1 and (station == "packing" or self.labour[m] < self.cooks)
                   for m in range(start, start + duration)):
                return start
        raise ValueError("Work exceeds the bounded planning horizon")

    def reserve(self, task_id: str, order_id: str, station: str, start: int, duration: int,
                item: str, frozen: bool = False) -> dict:
        end = start + duration
        if start < self.now or duration < 1 or end > self.horizon:
            raise ValueError("Reservation outside the planning horizon")
        for m in range(start, end):
            self.occupancy[station][m] += 1
            if station != "packing":
                self.labour[m] += 1
        row = {"task_id": task_id, "order_id": order_id, "station": station,
               "start": start, "end": end, "item": item, "frozen": frozen}
        self.rows.append(row)
        return row

    def place(self, task_id: str, order_id: str, station: str, earliest: int, duration: int, item: str) -> dict:
        return self.reserve(task_id, order_id, station, self.find_slot(station, earliest, duration), duration, item)
