import os

from django.test.runner import DiscoverRunner


TRUE_VALUES = {"1", "true", "yes", "on"}


class KabinetTestRunner(DiscoverRunner):
    """Keep the default local test command quick while preserving opt-in slow checks."""

    def __init__(self, *args, tags=None, exclude_tags=None, **kwargs):
        exclude_tags = set(exclude_tags or [])
        run_slow_tests = os.getenv("KABINET_RUN_SLOW_TESTS", "").lower() in TRUE_VALUES

        if not run_slow_tests and not tags:
            exclude_tags.add("slow")

        super().__init__(*args, tags=tags, exclude_tags=exclude_tags, **kwargs)
