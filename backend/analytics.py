import hashlib
import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone

from database import Database

ACTIVE_TTL_SECONDS = 90
RETENTION_DAYS = 35

_BOT_RE = re.compile(
    r"bot|crawl|spider|slurp|mediapartners|headless|python-requests|curl/|wget/|"
    r"go-http|semrush|ahrefs|petalbot|yandexbot|bingbot|googlebot|facebookexternalhit",
    re.I,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _utc_today() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _day_list(days: int) -> list[str]:
    end = _utc_today().date()
    start = end - timedelta(days=days - 1)
    return [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]


class AnalyticsTracker:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._init_schema()

    def _init_schema(self) -> None:
        with self.db.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS analytics_sessions (
                    session_id TEXT PRIMARY KEY,
                    visitor_hash TEXT NOT NULL,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    last_path TEXT,
                    page_views INTEGER NOT NULL DEFAULT 1,
                    is_bot INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_analytics_last_seen ON analytics_sessions(last_seen);

                CREATE TABLE IF NOT EXISTS analytics_daily (
                    day TEXT PRIMARY KEY,
                    page_views INTEGER NOT NULL DEFAULT 0,
                    unique_visitors INTEGER NOT NULL DEFAULT 0,
                    peak_online INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS analytics_daily_visitors (
                    day TEXT NOT NULL,
                    visitor_hash TEXT NOT NULL,
                    PRIMARY KEY (day, visitor_hash)
                );

                CREATE TABLE IF NOT EXISTS analytics_country_daily (
                    day TEXT NOT NULL,
                    country_code TEXT NOT NULL,
                    page_views INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (day, country_code)
                );

                CREATE TABLE IF NOT EXISTS analytics_ip_country (
                    ip TEXT PRIMARY KEY,
                    country_code TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def is_bot(ua: str | None) -> bool:
        if not ua:
            return False
        return bool(_BOT_RE.search(ua))

    @staticmethod
    def visitor_hash(ip: str, ua: str | None) -> str:
        raw = f"{ip}|{ua or ''}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    @staticmethod
    def _is_private_ip(ip: str) -> bool:
        if not ip:
            return True
        if ip == "::1" or ip.startswith("127."):
            return True
        if ip.startswith("10.") or ip.startswith("192.168.") or ip.startswith("169.254."):
            return True
        if ip.startswith("fc") or ip.startswith("fd"):
            return True
        if ip.startswith("fe80:"):
            return True
        parts = ip.split(".")
        if len(parts) == 4 and parts[0] == "172":
            try:
                second = int(parts[1])
                if 16 <= second <= 31:
                    return True
            except ValueError:
                pass
        return False

    @staticmethod
    def _lookup_country_ip(ip: str) -> str:
        if AnalyticsTracker._is_private_ip(ip):
            return "UN"
        try:
            req = urllib.request.Request(
                f"http://ip-api.com/json/{ip}?fields=countryCode",
                headers={"User-Agent": "yts-analytics/1.0"},
            )
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                data = json.loads(resp.read().decode())
            code = str(data.get("countryCode") or "").upper()
            if len(code) == 2:
                return code
        except Exception:
            pass
        return "UN"

    def _resolve_country(self, conn, ip: str, header_country: str | None) -> str:
        if header_country and header_country != "UN":
            return header_country
        row = conn.execute(
            "SELECT country_code FROM analytics_ip_country WHERE ip = ?",
            (ip,),
        ).fetchone()
        if row:
            return str(row["country_code"])
        code = self._lookup_country_ip(ip)
        conn.execute(
            """
            INSERT OR REPLACE INTO analytics_ip_country (ip, country_code, updated_at)
            VALUES (?, ?, ?)
            """,
            (ip, code, _now_iso()),
        )
        return code

    def record_ping(
        self,
        session_id: str,
        path: str,
        ip: str,
        ua: str | None,
        country: str | None = None,
    ) -> None:
        if not session_id or len(session_id) > 64 or self.is_bot(ua):
            return

        path = (path or "/")[:500]
        now = _now_iso()
        day = _today()
        vhash = self.visitor_hash(ip, ua)
        cutoff_active = (datetime.now(timezone.utc) - timedelta(seconds=ACTIVE_TTL_SECONDS)).isoformat()

        with self.db.connect() as conn:
            country_code = self._resolve_country(conn, ip, country)

            row = conn.execute(
                "SELECT last_path, page_views FROM analytics_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()

            if row:
                path_changed = row["last_path"] != path
                page_views = row["page_views"] + (1 if path_changed else 0)
                conn.execute(
                    """
                    UPDATE analytics_sessions
                    SET last_seen = ?, last_path = ?, page_views = ?, visitor_hash = ?
                    WHERE session_id = ?
                    """,
                    (now, path, page_views, vhash, session_id),
                )
            else:
                path_changed = True
                conn.execute(
                    """
                    INSERT INTO analytics_sessions
                    (session_id, visitor_hash, first_seen, last_seen, last_path, page_views)
                    VALUES (?, ?, ?, ?, ?, 1)
                    """,
                    (session_id, vhash, now, now, path),
                )

            if path_changed:
                conn.execute(
                    """
                    INSERT INTO analytics_daily (day, page_views, unique_visitors, peak_online)
                    VALUES (?, 1, 0, 0)
                    ON CONFLICT(day) DO UPDATE SET page_views = page_views + 1
                    """,
                    (day,),
                )
                conn.execute(
                    """
                    INSERT INTO analytics_country_daily (day, country_code, page_views)
                    VALUES (?, ?, 1)
                    ON CONFLICT(day, country_code) DO UPDATE SET page_views = page_views + 1
                    """,
                    (day, country_code),
                )

            if conn.execute(
                "INSERT OR IGNORE INTO analytics_daily_visitors (day, visitor_hash) VALUES (?, ?)",
                (day, vhash),
            ).rowcount:
                conn.execute(
                    """
                    INSERT INTO analytics_daily (day, page_views, unique_visitors, peak_online)
                    VALUES (?, 0, 1, 0)
                    ON CONFLICT(day) DO UPDATE SET unique_visitors = unique_visitors + 1
                    """,
                    (day,),
                )

            active = conn.execute(
                "SELECT COUNT(*) AS c FROM analytics_sessions WHERE last_seen >= ? AND is_bot = 0",
                (cutoff_active,),
            ).fetchone()["c"]
            conn.execute(
                """
                INSERT INTO analytics_daily (day, page_views, unique_visitors, peak_online)
                VALUES (?, 0, 0, ?)
                ON CONFLICT(day) DO UPDATE SET peak_online = MAX(peak_online, excluded.peak_online)
                """,
                (day, active),
            )

            self._prune_old(conn)

    def _prune_old(self, conn) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
        conn.execute("DELETE FROM analytics_sessions WHERE last_seen < ?", (cutoff,))
        old_day = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%d")
        conn.execute("DELETE FROM analytics_daily_visitors WHERE day < ?", (old_day,))
        conn.execute("DELETE FROM analytics_daily WHERE day < ?", (old_day,))
        conn.execute("DELETE FROM analytics_country_daily WHERE day < ?", (old_day,))

    def _countries_for_period(self, conn, days: int) -> list[dict[str, int | str]]:
        day_keys = _day_list(days)
        start_day, end_day = day_keys[0], day_keys[-1]
        rows = conn.execute(
            """
            SELECT country_code, SUM(page_views) AS page_views
            FROM analytics_country_daily
            WHERE day >= ? AND day <= ?
            GROUP BY country_code
            ORDER BY page_views DESC
            LIMIT 40
            """,
            (start_day, end_day),
        ).fetchall()
        return [
            {"country_code": str(r["country_code"]), "page_views": int(r["page_views"])}
            for r in rows
        ]

    def active_count(self) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=ACTIVE_TTL_SECONDS)).isoformat()
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM analytics_sessions WHERE last_seen >= ? AND is_bot = 0",
                (cutoff,),
            ).fetchone()
        return int(row["c"] if row else 0)

    def _period_summary(self, conn, days: int) -> dict[str, int]:
        day_keys = _day_list(days)
        start_day, end_day = day_keys[0], day_keys[-1]
        start_iso = f"{start_day}T"

        views_row = conn.execute(
            """
            SELECT COALESCE(SUM(page_views), 0) AS total
            FROM analytics_daily
            WHERE day >= ? AND day <= ?
            """,
            (start_day, end_day),
        ).fetchone()

        unique_row = conn.execute(
            """
            SELECT COUNT(DISTINCT visitor_hash) AS total
            FROM analytics_daily_visitors
            WHERE day >= ? AND day <= ?
            """,
            (start_day, end_day),
        ).fetchone()

        peak_row = conn.execute(
            """
            SELECT COALESCE(MAX(peak_online), 0) AS peak
            FROM analytics_daily
            WHERE day >= ? AND day <= ?
            """,
            (start_day, end_day),
        ).fetchone()

        avg_row = conn.execute(
            """
            SELECT AVG((julianday(last_seen) - julianday(first_seen)) * 86400) AS avg_sec
            FROM analytics_sessions
            WHERE is_bot = 0 AND first_seen >= ?
            """,
            (start_iso,),
        ).fetchone()

        return {
            "days": days,
            "page_views": int(views_row["total"] if views_row else 0),
            "unique_visitors": int(unique_row["total"] if unique_row else 0),
            "peak_online": int(peak_row["peak"] if peak_row else 0),
            "avg_duration_seconds": int(avg_row["avg_sec"] or 0) if avg_row else 0,
        }

    def _daily_series(self, conn, days: int) -> list[dict[str, int | str]]:
        day_keys = _day_list(days)
        start_day, end_day = day_keys[0], day_keys[-1]
        rows = conn.execute(
            """
            SELECT day, page_views, unique_visitors, peak_online
            FROM analytics_daily
            WHERE day >= ? AND day <= ?
            ORDER BY day ASC
            """,
            (start_day, end_day),
        ).fetchall()
        by_day = {r["day"]: r for r in rows}
        series: list[dict[str, int | str]] = []
        for day in day_keys:
            row = by_day.get(day)
            series.append(
                {
                    "day": day,
                    "page_views": int(row["page_views"]) if row else 0,
                    "unique_visitors": int(row["unique_visitors"]) if row else 0,
                    "peak_online": int(row["peak_online"]) if row else 0,
                }
            )
        return series

    def get_stats(self) -> dict:
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(seconds=ACTIVE_TTL_SECONDS)).isoformat()
        day = _today()

        with self.db.connect() as conn:
            active_now = conn.execute(
                "SELECT COUNT(*) AS c FROM analytics_sessions WHERE last_seen >= ? AND is_bot = 0",
                (cutoff,),
            ).fetchone()["c"]

            daily_today = conn.execute(
                "SELECT page_views, unique_visitors, peak_online FROM analytics_daily WHERE day = ?",
                (day,),
            ).fetchone()

            avg_row = conn.execute(
                """
                SELECT AVG((julianday(last_seen) - julianday(first_seen)) * 86400) AS avg_sec
                FROM analytics_sessions
                WHERE is_bot = 0 AND first_seen >= ?
                """,
                (f"{day}T",),
            ).fetchone()

            recent = conn.execute(
                """
                SELECT last_path, COUNT(*) AS c
                FROM analytics_sessions
                WHERE last_seen >= ? AND is_bot = 0
                GROUP BY last_path
                ORDER BY c DESC
                LIMIT 10
                """,
                (cutoff,),
            ).fetchall()

            periods = {
                "3": self._period_summary(conn, 3),
                "7": self._period_summary(conn, 7),
                "30": self._period_summary(conn, 30),
            }
            daily = self._daily_series(conn, 30)
            countries = {
                "3": self._countries_for_period(conn, 3),
                "7": self._countries_for_period(conn, 7),
                "30": self._countries_for_period(conn, 30),
            }

        avg_seconds = int(avg_row["avg_sec"] or 0) if avg_row else 0

        return {
            "active_now": active_now,
            "today_page_views": daily_today["page_views"] if daily_today else 0,
            "today_unique": daily_today["unique_visitors"] if daily_today else 0,
            "peak_today": daily_today["peak_online"] if daily_today else 0,
            "avg_duration_seconds": avg_seconds,
            "active_pages": [{"path": r["last_path"] or "/", "count": r["c"]} for r in recent],
            "periods": periods,
            "daily": daily,
            "countries": countries,
        }
