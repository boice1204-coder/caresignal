"""
Data access layer for CareSignal.

Two implementations share one interface (`DataSource`):

  * `BigQueryDataSource`  — production. Runs parameterized SQL against the
                             `caresignal` dataset defined in sql/schema.sql.
  * `LocalDataSource`     — local/demo. Reads the same shape of data out of
                             an in-memory pandas DataFrame (loaded from
                             data/sample_events.json). Used for the hackathon
                             demo, unit tests, and anywhere a GCP project
                             isn't wired up yet.

The decision engine only ever talks to `DataSource`, so swapping Local ->
BigQuery at deploy time is a one-line change (see pipeline/run_pipeline.py).
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
import json
import pandas as pd


@dataclass
class Event:
    event_id: str
    subject_id: str
    caregiver_id: Optional[str]
    logged_at: datetime
    source: Optional[str] = None
    fields: dict = field(default_factory=dict)  # metric-specific payload


class DataSource(ABC):
    """Common interface the decision engine depends on."""

    @abstractmethod
    def get_meds(self, subject_id: str, since: datetime) -> list[Event]: ...

    @abstractmethod
    def get_vitals(self, subject_id: str, metric: str, since: datetime) -> list[Event]: ...

    @abstractmethod
    def get_meals(self, subject_id: str, since: datetime) -> list[Event]: ...


# ---------------------------------------------------------------------------
# Local / demo implementation
# ---------------------------------------------------------------------------
class LocalDataSource(DataSource):
    """Loads sample_events.json into pandas DataFrames and serves the same
    query shape BigQuery would. This is what the hackathon demo and the
    unit tests run against — no GCP project required."""

    def __init__(self, fixture_path: str):
        with open(fixture_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        self.meds = pd.DataFrame(raw.get("meds_log", []))
        self.vitals = pd.DataFrame(raw.get("vitals_log", []))
        self.meals = pd.DataFrame(raw.get("meal_log", []))
        for df in (self.meds, self.vitals, self.meals):
            if not df.empty:
                df["logged_at"] = pd.to_datetime(df["logged_at"])

    def _rows_to_events(self, df: pd.DataFrame, extra_fields: list[str]) -> list[Event]:
        out = []
        for _, r in df.iterrows():
            out.append(Event(
                event_id=r["event_id"],
                subject_id=r["subject_id"],
                caregiver_id=r.get("caregiver_id"),
                logged_at=r["logged_at"].to_pydatetime(),
                source=r.get("source"),
                fields={k: r[k] for k in extra_fields if k in r},
            ))
        return out

    def get_meds(self, subject_id: str, since: datetime) -> list[Event]:
        if self.meds.empty:
            return []
        df = self.meds[(self.meds.subject_id == subject_id) & (self.meds.logged_at >= since)]
        return self._rows_to_events(df, ["drug_name", "dose_mg", "frequency", "is_supplement"])

    def get_vitals(self, subject_id: str, metric: str, since: datetime) -> list[Event]:
        if self.vitals.empty:
            return []
        df = self.vitals[
            (self.vitals.subject_id == subject_id)
            & (self.vitals.metric == metric)
            & (self.vitals.logged_at >= since)
        ].sort_values("logged_at")
        return self._rows_to_events(df, ["metric", "value", "unit"])

    def get_meals(self, subject_id: str, since: datetime) -> list[Event]:
        if self.meals.empty:
            return []
        df = self.meals[(self.meals.subject_id == subject_id) & (self.meals.logged_at >= since)]
        return self._rows_to_events(df, ["meal", "status", "note"])


# ---------------------------------------------------------------------------
# Production implementation
# ---------------------------------------------------------------------------
class BigQueryDataSource(DataSource):
    """Talks to the real `caresignal` BigQuery dataset. Queries are
    parameterized (no string-built SQL) to avoid injection and to let
    BigQuery cache query plans."""

    def __init__(self, project_id: str):
        from google.cloud import bigquery  # imported lazily so LocalDataSource
        self._bq = bigquery.Client(project=project_id)          # doesn't require the dependency at import time
        self._bigquery = bigquery

    def _query(self, sql: str, subject_id: str, since: datetime, **kw) -> pd.DataFrame:
        job_config = self._bigquery.QueryJobConfig(query_parameters=[
            self._bigquery.ScalarQueryParameter("subject_id", "STRING", subject_id),
            self._bigquery.ScalarQueryParameter("since", "TIMESTAMP", since),
            *[self._bigquery.ScalarQueryParameter(k, "STRING", v) for k, v in kw.items()],
        ])
        return self._bq.query(sql, job_config=job_config).to_dataframe()

    def get_meds(self, subject_id: str, since: datetime) -> list[Event]:
        sql = """
            SELECT event_id, subject_id, caregiver_id, drug_name, dose_mg,
                   frequency, is_supplement, source, logged_at
            FROM `caresignal.meds_log`
            WHERE subject_id = @subject_id AND logged_at >= @since
            ORDER BY logged_at DESC
        """
        df = self._query(sql, subject_id, since)
        return _df_to_events(df, ["drug_name", "dose_mg", "frequency", "is_supplement"])

    def get_vitals(self, subject_id: str, metric: str, since: datetime) -> list[Event]:
        sql = """
            SELECT event_id, subject_id, caregiver_id, metric, value, unit, source, logged_at
            FROM `caresignal.vitals_log`
            WHERE subject_id = @subject_id AND metric = @metric AND logged_at >= @since
            ORDER BY logged_at ASC
        """
        df = self._query(sql, subject_id, since, metric=metric)
        return _df_to_events(df, ["metric", "value", "unit"])

    def get_meals(self, subject_id: str, since: datetime) -> list[Event]:
        sql = """
            SELECT event_id, subject_id, caregiver_id, meal, status, note, logged_at
            FROM `caresignal.meal_log`
            WHERE subject_id = @subject_id AND logged_at >= @since
            ORDER BY logged_at DESC
        """
        df = self._query(sql, subject_id, since)
        return _df_to_events(df, ["meal", "status", "note"])


def _df_to_events(df: pd.DataFrame, extra_fields: list[str]) -> list[Event]:
    out = []
    for _, r in df.iterrows():
        out.append(Event(
            event_id=r["event_id"],
            subject_id=r["subject_id"],
            caregiver_id=r.get("caregiver_id"),
            logged_at=r["logged_at"],
            source=r.get("source"),
            fields={k: r[k] for k in extra_fields if k in r},
        ))
    return out
