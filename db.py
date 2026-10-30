"""Слой хранения данных: база SQLite3.

Создаёт таблицу reminders при старте (если её нет) и предоставляет
все операции для работы с напоминаниями: добавление, удаление,
смена статуса, выборка с фильтром, поиск сработавших.
"""

import os
import sqlite3
from datetime import datetime, timedelta

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reminders.db")

STATUS_PENDING = "Ожидает"
STATUS_DONE = "Готово"
STATUS_OVERDUE = "Просрочено"
STATUS_CANCELLED = "Отменено"

ALL_STATUSES = (STATUS_PENDING, STATUS_DONE, STATUS_OVERDUE, STATUS_CANCELLED)

DATETIME_FORMAT = "%Y-%m-%d %H:%M"


def now_str():
    """Текущая локальная дата/время в формате хранения."""
    return datetime.now().strftime(DATETIME_FORMAT)


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
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    title       TEXT    NOT NULL,
                    description TEXT    NOT NULL DEFAULT '',
                    trigger_at  TEXT    NOT NULL,
                    status      TEXT    NOT NULL DEFAULT '{STATUS_PENDING}',
                    notified    INTEGER NOT NULL DEFAULT 0,
                    created_at  TEXT    NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reminders_status ON reminders (status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reminders_trigger ON reminders (trigger_at)"
            )
            conn.commit()
        finally:
            conn.close()

    def add_reminder(self, title, description, trigger_at):
        """Создаёт напоминание в статусе 'Ожидает', возвращает его id."""
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO reminders"
                " (title, description, trigger_at, status, notified, created_at)"
                " VALUES (?, ?, ?, ?, 0, ?)",
                (title, description, trigger_at, STATUS_PENDING, now_str()),
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
