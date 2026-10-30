"""Напоминалка: главное окно на tkinter и планировщик уведомлений.

Запуск:  python app.py
БД создаётся автоматически рядом с файлами проекта (reminders.db).
"""

import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox, ttk

from db import (
    ALL_STATUSES,
    DATETIME_FORMAT,
    STATUS_CANCELLED,
    STATUS_DONE,
    STATUS_OVERDUE,
    STATUS_PENDING,
    ReminderDB,
    now_str,
)
from notifications import ReminderPopup, show_toast

CHECK_INTERVAL_MS = 5000
FILTER_ALL = "Все"
SNOOZE_MINUTES = 5


class ReminderApp:
    def __init__(self, root, db=None):
        self.root = root
        self.db = db or ReminderDB()
        self.popups = {}
        self._check_job = None

        self.root.title("Напоминалка")
        self.root.geometry("860x500")
        self.root.minsize(700, 380)

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.refresh()
        self._schedule_check(delay=1000)

    def _build_ui(self):
        toolbar = ttk.Frame(self.root, padding=(8, 8, 8, 4))
        toolbar.pack(fill="x")

        ttk.Label(toolbar, text="Фильтр по статусу:").pack(side="left")
        self.filter_var = tk.StringVar(value=FILTER_ALL)
        self.filter_box = ttk.Combobox(
            toolbar,
            textvariable=self.filter_var,
            state="readonly",
            width=13,
            values=[FILTER_ALL, *ALL_STATUSES],
        )
        self.filter_box.pack(side="left", padx=(6, 14))
        self.filter_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh())

        ttk.Button(toolbar, text="Добавить", command=self.add_reminder).pack(
            side="left", padx=3
        )
        ttk.Button(
            toolbar,
            text="Готово",
            command=lambda: self.set_status_selected(STATUS_DONE),
        ).pack(side="left", padx=3)
        ttk.Button(
            toolbar,
            text="Отменить",
            command=lambda: self.set_status_selected(STATUS_CANCELLED),
        ).pack(side="left", padx=3)
        ttk.Button(toolbar, text="Удалить", command=self.delete_selected).pack(
            side="left", padx=3
        )
        ttk.Button(toolbar, text="Обновить", command=self.refresh).pack(
            side="right", padx=3
        )

        self.status_var = tk.StringVar()
        ttk.Label(
            self.root, textvariable=self.status_var, anchor="w", padding=(8, 4)
        ).pack(fill="x", side="bottom")

        container = ttk.Frame(self.root)
        container.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        columns = ("time", "title", "description", "status")
        self.tree = ttk.Treeview(
            container, columns=columns, show="headings", selectmode="browse"
        )
        headers = {
            "time": "Время срабатывания",
            "title": "Заголовок",
            "description": "Описание",
            "status": "Статус",
        }
        widths = {"time": 150, "title": 200, "description": 300, "status": 110}
        for column in columns:
            self.tree.heading(column, text=headers[column])
            self.tree.column(
                column, width=widths[column], anchor="w", stretch=column == "description"
            )
        self.tree.column("time", anchor="center")
        self.tree.column("status", anchor="center")

        scrollbar = ttk.Scrollbar(
            container, orient="vertical", command=self.tree.yview
        )
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.tree.tag_configure(STATUS_PENDING, foreground="#1a1a1a")
        self.tree.tag_configure(STATUS_DONE, foreground="#1e7d32")
        self.tree.tag_configure(STATUS_OVERDUE, foreground="#c62828")
        self.tree.tag_configure(STATUS_CANCELLED, foreground="#757575")

    def refresh(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        status = self.filter_var.get()
        rows = self.db.get_reminders(None if status == FILTER_ALL else status)
        for row in rows:
            self.tree.insert(
                "",
                "end",
                iid=str(row["id"]),
                values=(
                    row["trigger_at"],
                    row["title"],
                    row["description"],
                    row["status"],
                ),
                tags=(row["status"],),
            )

        counts = self.db.count_by_status()
        total = sum(counts.values())
        self.status_var.set(
            f"Всего: {total}  |  {STATUS_PENDING}: {counts[STATUS_PENDING]}  |  "
            f"{STATUS_OVERDUE}: {counts[STATUS_OVERDUE]}  |  "
            f"{STATUS_DONE}: {counts[STATUS_DONE]}  |  "
            f"{STATUS_CANCELLED}: {counts[STATUS_CANCELLED]}"
        )

    def _selected_id(self):
        selection = self.tree.selection()
        return int(selection[0]) if selection else None

    def add_reminder(self):
        dialog = AddReminderDialog(self.root)
        self.root.wait_window(dialog)
        if dialog.result:
            self.db.add_reminder(**dialog.result)
            self.refresh()

    def delete_selected(self):
        reminder_id = self._selected_id()
        if reminder_id is None:
            messagebox.showinfo("Нет выбора", "Выберите напоминание в списке.")
            return
        reminder = self.db.get_reminder(reminder_id)
        if messagebox.askyesno(
            "Удаление", f"Удалить напоминание «{reminder['title']}»?"
        ):
            self.db.delete_reminder(reminder_id)
            self.refresh()

    def set_status_selected(self, status):
        reminder_id = self._selected_id()
        if reminder_id is None:
            messagebox.showinfo("Нет выбора", "Выберите напоминание в списке.")
            return
        self.db.set_status(reminder_id, status)
        self.refresh()

    def _schedule_check(self, delay=CHECK_INTERVAL_MS):
        self._check_job = self.root.after(delay, self.check_due)

    def check_due(self):
        try:
            due = self.db.get_due_reminders()
            if due:
                for reminder in due:
                    self.db.mark_notified(reminder["id"])
                    self.db.set_status(reminder["id"], STATUS_OVERDUE)
                    self._show_notification(reminder)
                self.refresh()
        finally:
            self._schedule_check()

    def _show_notification(self, reminder):
        self._prune_popups()
        show_toast(
            f"Напоминание: {reminder['title']}",
            reminder["description"] or reminder["trigger_at"],
        )
        popup = ReminderPopup(
            self.root,
            reminder,
            on_done=self._mark_done_from_popup,
            on_snooze=self._snooze_from_popup,
        )
        self.popups[reminder["id"]] = popup

    def _prune_popups(self):
        for reminder_id in [
            rid
            for rid, popup in self.popups.items()
            if not self._popup_alive(popup)
        ]:
            self.popups.pop(reminder_id, None)

    @staticmethod
    def _popup_alive(popup):
        try:
            return bool(popup.winfo_exists())
        except tk.TclError:
            return False

    def _mark_done_from_popup(self, reminder_id):
        self.db.set_status(reminder_id, STATUS_DONE)
        self.refresh()

    def _snooze_from_popup(self, reminder_id):
        self.db.snooze_reminder(reminder_id, minutes=SNOOZE_MINUTES)
        self.refresh()

    def _on_close(self):
        if self._check_job is not None:
            self.root.after_cancel(self._check_job)
        for popup in list(self.popups.values()):
            if self._popup_alive(popup):
                popup.destroy()
        self.root.destroy()


class AddReminderDialog(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Новое напоминание")
        self.resizable(False, False)
        self.result = None
        self.transient(master)
        self.grab_set()
        self.bind("<Return>", lambda _event: self._save())
        self.bind("<Escape>", lambda _event: self.destroy())

        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Заголовок:").grid(row=0, column=0, sticky="w")
        self.title_var = tk.StringVar()
        self.title_entry = ttk.Entry(frame, textvariable=self.title_var, width=46)
        self.title_entry.grid(row=1, column=0, columnspan=2, sticky="we", pady=(2, 10))

        ttk.Label(frame, text="Описание:").grid(row=2, column=0, sticky="w")
        self.description_text = tk.Text(frame, width=44, height=4)
        self.description_text.grid(
            row=3, column=0, columnspan=2, sticky="we", pady=(2, 10)
        )

        ttk.Label(frame, text="Дата (ГГГГ-ММ-ДД):").grid(
            row=4, column=0, sticky="w", pady=(0, 4)
        )
        soon = (datetime.now() + timedelta(minutes=10)).replace(
            second=0, microsecond=0
        )
        self.date_var = tk.StringVar(value=soon.strftime("%Y-%m-%d"))
        ttk.Entry(frame, textvariable=self.date_var, width=13).grid(
            row=4, column=1, sticky="w", pady=(0, 4)
        )

        ttk.Label(frame, text="Время (ЧЧ:ММ):").grid(
            row=5, column=0, sticky="w", pady=(0, 10)
        )
        self.time_var = tk.StringVar(value=soon.strftime("%H:%M"))
        ttk.Entry(frame, textvariable=self.time_var, width=13).grid(
            row=5, column=1, sticky="w", pady=(0, 10)
        )

        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="Сохранить", command=self._save).pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(buttons, text="Отмена", command=self.destroy).pack(side="left")

        self.title_entry.focus_set()

        self.update_idletasks()
        x = master.winfo_rootx() + max(
            (master.winfo_width() - self.winfo_width()) // 2, 0
        )
        y = master.winfo_rooty() + max(
            (master.winfo_height() - self.winfo_height()) // 3, 0
        )
        self.geometry(f"+{x}+{y}")

    def _save(self):
        title = self.title_var.get().strip()
        if not title:
            messagebox.showerror(
                "Ошибка", "Укажите заголовок напоминания.", parent=self
            )
            return
        description = self.description_text.get("1.0", "end").strip()
        try:
            trigger_at = datetime.strptime(
                f"{self.date_var.get().strip()} {self.time_var.get().strip()}",
                DATETIME_FORMAT,
            )
        except ValueError:
            messagebox.showerror(
                "Ошибка",
                "Неверный формат даты или времени.\n"
                "Дата: ГГГГ-ММ-ДД, время: ЧЧ:ММ.",
                parent=self,
            )
            return
        if trigger_at < datetime.now() and not messagebox.askyesno(
            "Внимание",
            "Указанное время уже прошло.\n"
            "Напоминание сразу станет просроченным. Сохранить?",
            parent=self,
        ):
            return
        self.result = {
            "title": title,
            "description": description,
            "trigger_at": trigger_at.strftime(DATETIME_FORMAT),
        }
        self.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style(root).theme_use("vista")
    except tk.TclError:
        pass
    ReminderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
