"""Слой хранения данных: база SQLite3.

Создаёт таблицу reminders при старте (если её нет) и предоставляет
все операции для работы с напоминаниями: добавление, удаление,
смена статуса, выборка с фильтром, поиск сработавших.
"""

import calendar
import os
import sqlite3
from datetime import datetime, timedelta

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reminders.db")

STATUS_PENDING = "Ожидает"
STATUS_DONE = "Готово"
STATUS_OVERDUE = "Просрочено"
STATUS_CANCELLED = "Отменено"

ALL_STATUSES = (STATUS_PENDING, STATUS_DONE, STATUS_OVERDUE, STATUS_CANCELLED)

REPEAT_UNITS = ("minutes", "hours", "days", "weeks", "months", "years")

_REPEAT_SHORT = {
    "minutes": "мин",
    "hours": "ч",
    "days": "дн",
    "weeks": "нед",
    "months": "мес",
    "years": "г",
}

DATETIME_FORMAT = "%Y-%m-%d %H:%M"


def now_str():
    """Текущая локальная дата/время в формате хранения."""
    return datetime.now().strftime(DATETIME_FORMAT)


def format_repeat(repeat_every, repeat_unit):
    """Короткое описание повтора для таблицы, например 'каждые 2 нед'."""
    if repeat_every >= 1 and repeat_unit in REPEAT_UNITS:
        return f"каждые {repeat_every} {_REPEAT_SHORT[repeat_unit]}"
    return "—"


def compute_next_occurrence(trigger_at, repeat_every, repeat_unit):
    """Следующее срабатывание строго в будущем.

    Пропущенные периоды (пока приложение было закрыто) схлопываются
    в одно ближайшее будущее срабатывание. Для неповторяющихся
    напоминаний возвращает None.
    """
    if repeat_every < 1 or repeat_unit not in REPEAT_UNITS:
        return None
    moment = datetime.strptime(trigger_at, DATETIME_FORMAT)
    now = datetime.now()
    if repeat_unit == "months":
        while moment <= now:
            moment = _add_months(moment, repeat_every)
    elif repeat_unit == "years":
        while moment <= now:
            moment = _add_years(moment, repeat_every)
    else:
        steps = {
            "minutes": timedelta(minutes=repeat_every),
            "hours": timedelta(hours=repeat_every),
            "days": timedelta(days=repeat_every),
            "weeks": timedelta(weeks=repeat_every),
        }
        step = steps[repeat_unit]
        while moment <= now:
            moment += step
    return moment.strftime(DATETIME_FORMAT)


def _add_months(value, months):
    index = value.month - 1 + months
    year = value.year + index // 12
    month = index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _add_years(value, years):
    year = value.year + years
    day = min(value.day, calendar.monthrange(year, value.month)[1])
    return value.replace(year=year, day=day)


class ReminderDB:
    """Обёртка над SQLite3: соединение открывается на каждую операцию."""

    def __init__(self, db_path=DB_FILE):
        self.db_path = db_path
        self.init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        """Проверяет наличие таблиц/индексов и создаёт их при необходимости."""
        conn = self._connect()
        try:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS reminders (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    title        TEXT    NOT NULL,
                    description  TEXT    NOT NULL DEFAULT '',
                    trigger_at   TEXT    NOT NULL,
                    status       TEXT    NOT NULL DEFAULT '{STATUS_PENDING}',
                    notified     INTEGER NOT NULL DEFAULT 0,
                    repeat_every INTEGER NOT NULL DEFAULT 0,
                    repeat_unit  TEXT    NOT NULL DEFAULT 'none',
                    created_at   TEXT    NOT NULL
                )
                """
            )
            self._ensure_repeat_columns(conn)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reminders_status ON reminders (status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reminders_trigger ON reminders (trigger_at)"
            )
            conn.commit()
        finally:
            conn.close()

    def _ensure_repeat_columns(self, conn):
        """Миграция: добавляет колонки повтора в БД, созданную старой версией."""
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(reminders)")}
        if "repeat_every" not in existing:
            conn.execute(
                "ALTER TABLE reminders ADD COLUMN repeat_every INTEGER NOT NULL DEFAULT 0"
            )
        if "repeat_unit" not in existing:
            conn.execute(
                "ALTER TABLE reminders ADD COLUMN repeat_unit TEXT NOT NULL DEFAULT 'none'"
            )

    def add_reminder(self, title, description, trigger_at, repeat_every=0, repeat_unit="none"):
        """Создаёт напоминание в статусе 'Ожидает', возвращает его id.

        repeat_every >= 1 и repeat_unit из REPEAT_UNITS задают повтор
        (например, каждые 2 недели); repeat_every = 0 — без повтора.
        """
        if repeat_every >= 1 and repeat_unit not in REPEAT_UNITS:
            raise ValueError(f"Неизвестная единица повтора: {repeat_unit}")
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO reminders"
                " (title, description, trigger_at, status, notified,"
                "  repeat_every, repeat_unit, created_at)"
                " VALUES (?, ?, ?, ?, 0, ?, ?, ?)",
                (title, description, trigger_at, STATUS_PENDING,
                 repeat_every, repeat_unit, now_str()),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def delete_reminder(self, reminder_id):
        """Удаляет напоминание по id. Возвращает True, если строка удалена."""
        conn = self._connect()
        try:
            cur = conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def set_status(self, reminder_id, status):
        """Устанавливает статус напоминания ('Готово', 'Отменено' и т.д.)."""
        if status not in ALL_STATUSES:
            raise ValueError(f"Неизвестный статус: {status}")
        conn = self._connect()
        try:
            cur = conn.execute(
                "UPDATE reminders SET status = ? WHERE id = ?",
                (status, reminder_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def get_reminder(self, reminder_id):
        """Возвращает напоминание по id в виде словаря или None."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM reminders WHERE id = ?", (reminder_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_reminders(self, status=None):
        """Список напоминаний; при переданном статусе — фильтр по нему."""
        conn = self._connect()
        try:
            if status in ALL_STATUSES:
                rows = conn.execute(
                    "SELECT * FROM reminders WHERE status = ? ORDER BY trigger_at",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM reminders ORDER BY trigger_at"
                ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_due_reminders(self, current=None):
        """Напоминания 'Ожидает', время которых наступило и ещё не показанные."""
        current = current or now_str()
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM reminders"
                " WHERE status = ? AND notified = 0 AND trigger_at <= ?"
                " ORDER BY trigger_at",
                (STATUS_PENDING, current),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def mark_notified(self, reminder_id):
        """Помечает напоминание как показанное, чтобы не уведомлять повторно."""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE reminders SET notified = 1 WHERE id = ?", (reminder_id,)
            )
            conn.commit()
        finally:
            conn.close()

    def reschedule_reminder(self, reminder_id, trigger_at):
        """Переносит срабатывание на новое время и возвращает в 'Ожидает'."""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE reminders SET trigger_at = ?, status = ?, notified = 0"
                " WHERE id = ?",
                (trigger_at, STATUS_PENDING, reminder_id),
            )
            conn.commit()
        finally:
            conn.close()

    def snooze_reminder(self, reminder_id, minutes=5):
        """Откладывает напоминание: возвращает статус 'Ожидает' со сдвигом времени."""
        new_time = (
            datetime.now() + timedelta(minutes=minutes)
        ).strftime(DATETIME_FORMAT)
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE reminders SET trigger_at = ?, status = ?, notified = 0"
                " WHERE id = ?",
                (new_time, STATUS_PENDING, reminder_id),
            )
            conn.commit()
            return new_time
        finally:
            conn.close()

    def count_by_status(self):
        """Словарь {статус: количество} по всем статусам."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM reminders GROUP BY status"
            ).fetchall()
            counts = {status: 0 for status in ALL_STATUSES}
            counts.update({row["status"]: row["cnt"] for row in rows})
            return counts
        finally:
            conn.close()
