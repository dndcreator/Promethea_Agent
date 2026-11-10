"""Bounded retries for local atomic renames, never for business operations."""
import os
from time import sleep


def rename_with_retry(source, target, *, replace=False):
    operation = os.replace if replace else os.rename
    for attempt, delay in enumerate((0, 0.02, 0.08)):
        if delay:
            sleep(delay)
        try:
            operation(source, target)
            return
        except PermissionError as error:
            # A transient Windows sharing/access error must not become a delete,
            # permission change, or replay of the operation that produced data.
            if getattr(error, "winerror", None) not in {5, 32, 33} or attempt == 2:
                raise
