"""Уведомления: системный toast Windows (winotify -> win10toast) и
всплывающее окно поверх всех окон на tkinter.

Модуль не зависит от логики приложения и работает, даже если главное
окно свернуто: mainloop tkinter продолжает обрабатывать события,
а toast отправляется средствами системы.
"""

import itertools
import tkinter as tk

AUTO_CLOSE_MS = 30_000


def show_toast(title, message):
    """Показывает системное уведомление Windows.

    Пробует winotify, затем win10toast. Возвращает True при успехе.
    """
    for backend in (_toast_winotify, _toast_win10toast):
        try:
            backend(title, message)
            return True
        except Exception:
            continue
    return False


def _toast_winotify(title, message):
    from winotify import Notification, audio

    toast = Notification(
        app_id="Напоминалка",
        title=title,
        msg=message,
        duration="short",
    )
    toast.set_audio(audio.Default, loop=False)
    toast.show()


def _toast_win10toast(title, message):
    from win10toast import ToastNotifier

    ToastNotifier().show_toast(title, message, duration=5, threaded=True)


class ReminderPopup(tk.Toplevel):
    """Всплывающее окно поверх всех окон с кнопками 'Готово'/'Отложить'."""

    _offsets = itertools.cycle(range(0, 240, 40))

    def __init__(self, master, reminder, on_done=None, on_snooze=None, repeat_note=None):
        super().__init__(master)
        self.reminder = reminder
        self.on_done = on_done
        self.on_snooze = on_snooze

        self.title("Напоминание")
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._destroy)

        frame = tk.Frame(self, padx=16, pady=12)
        frame.pack(fill="both", expand=True)

        tk.Label(
            frame,
            text=reminder["title"],
            font=("Segoe UI", 13, "bold"),
            wraplength=340,
            justify="left",
        ).pack(anchor="w")

        if reminder.get("description"):
            tk.Label(
                frame,
                text=reminder["description"],
                wraplength=340,
                justify="left",
            ).pack(anchor="w", pady=(6, 0))

        tk.Label(
            frame,
            text=f"Время срабатывания: {reminder['trigger_at']}",
            fg="#555555",
        ).pack(anchor="w", pady=(6, 2))

        if repeat_note:
            tk.Label(frame, text=repeat_note, fg="#555555").pack(
                anchor="w", pady=(0, 12)
            )
        else:
            tk.Label(frame, text="").pack(anchor="w", pady=(0, 12))

        buttons = tk.Frame(frame)
        buttons.pack(fill="x")
        tk.Button(
            buttons, text="Готово", width=12, command=self._handle_done
        ).pack(side="left", padx=(0, 8))
        if on_snooze is not None:
            tk.Button(
                buttons, text="Отложить 5 мин", command=self._handle_snooze
            ).pack(side="left", padx=(0, 8))
        tk.Button(
            buttons, text="Закрыть", width=10, command=self._destroy
        ).pack(side="right")

        self._place_bottom_right()
        self.lift()
        self.focus_force()
        self._auto_close_job = self.after(AUTO_CLOSE_MS, self._destroy)

    def _place_bottom_right(self):
        self.update_idletasks()
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        offset = next(self._offsets)
        x = max(screen_w - width - 60 - offset, 0)
        y = max(screen_h - height - 120 - offset, 0)
        self.geometry(f"+{x}+{y}")

    def _handle_done(self):
        if self.on_done is not None:
            self.on_done(self.reminder["id"])
        self._destroy()

    def _handle_snooze(self):
        if self.on_snooze is not None:
            self.on_snooze(self.reminder["id"])
        self._destroy()

    def _destroy(self):
        try:
            self.after_cancel(self._auto_close_job)
        except Exception:
            pass
        self.destroy()
