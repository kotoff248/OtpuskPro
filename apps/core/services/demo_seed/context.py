from dataclasses import dataclass
from datetime import date
from random import Random

from apps.core.services.demo_seed.constants import (
    FEMALE_FIRST_NAMES,
    FEMALE_LAST_NAMES,
    FEMALE_MIDDLE_NAMES,
    MALE_FIRST_NAMES,
    MALE_LAST_NAMES,
    MALE_MIDDLE_NAMES,
    SURNAME_PAIRS,
)


@dataclass(frozen=True)
class DemoSeedContext:
    seed_value: int
    history_years: int
    fast_mode: bool
    progress_job_id: int | None
    today: date
    rng: Random


class NameFactory:
    def __init__(self, rng):
        self.rng = rng
        self._surname_pairs = list(SURNAME_PAIRS)
        self.rng.shuffle(self._surname_pairs)
        self._counters = {"male": 0, "female": 0}
        self._global_counter = 0

    def next_name(self, gender):
        counter = self._counters[gender]
        self._counters[gender] += 1
        global_counter = self._global_counter
        self._global_counter += 1

        if gender == "female":
            first_names = FEMALE_FIRST_NAMES
            middle_names = FEMALE_MIDDLE_NAMES
            last_name = self._surname_pairs[global_counter % len(self._surname_pairs)][1]
        else:
            first_names = MALE_FIRST_NAMES
            middle_names = MALE_MIDDLE_NAMES
            last_name = self._surname_pairs[global_counter % len(self._surname_pairs)][0]

        return (
            last_name,
            first_names[counter % len(first_names)],
            middle_names[((counter // (len(first_names) * len(self._surname_pairs))) + counter) % len(middle_names)],
        )
