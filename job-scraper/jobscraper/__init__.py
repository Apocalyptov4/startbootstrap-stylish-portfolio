"""Aggregate job openings from public job-board APIs into one searchable list."""

from .models import Job
from .scraper import Filters, run

__version__ = "0.1.0"
__all__ = ["Job", "Filters", "run"]
