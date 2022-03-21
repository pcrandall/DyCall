# -*- coding: utf-8 -*-
# pylint: disable=too-many-locals

from __future__ import annotations

import logging
import platform
import queue
from typing import NamedTuple

import tksheet
import ttkbootstrap as tk
from ttkbootstrap import ttk
from ttkbootstrap.localization import MessageCatalog as MsgCat

from dycall.runner import Runner
from dycall.types import CALL_CONVENTIONS, PARAMETER_TYPES, Marshaller, RunResult
from dycall.util import DARK_THEME

log = logging.getLogger(__name__)


class FunctionFrame(ttk.Frame):
    def __init__(
        self,
        parent: tk.Window,
        call_conv: tk.StringVar,
        returns: tk.StringVar,
        lib_path: tk.StringVar,
        export: tk.StringVar,
        output: tk.StringVar,
        status: tk.StringVar,
        is_outmode: tk.BooleanVar,
        is_running: tk.BooleanVar,
        exc_type: tk.StringVar,
        rows_to_add: int,
    ):
        super().__init__()
        self.__parent = parent
        self.__call_conv = call_conv
        self.__returns = returns
        self.__lib_path = lib_path
        self.__export = export
        self.__output = output
        self.__status = status
        self.__is_outmode = is_outmode
        self.__is_running = is_running
        self.__exc_type = exc_type
        self.__res_q = queue.Queue()  # type: ignore
        self.__exc_q = queue.Queue()  # type: ignore
        self.__args: list[list[str]] = []
        self.__is_windows = platform.system() == "Windows"

        # Call convention
        if self.__is_windows:
            cg = ttk.Labelframe(self, text="Calling Convention")
            self.cc = cc = ttk.Combobox(
                cg,
                values=CALL_CONVENTIONS,
                textvariable=call_conv,
                state="disabled",
                font=("Courier", 9),
            )
            if not call_conv.get():
                cc.current(0)  # CallConvention.cdecl

        # Return type
        rg = ttk.Labelframe(self, text="Returns")
        self.rc = rc = ttk.Combobox(
            rg,
            values=PARAMETER_TYPES,
            textvariable=returns,
            state="disabled",
            font=("Courier", 9),
        )
        if not returns.get():
            rc.current(7)  # ParameterType.i (int32_t)

        # Run
        self.rb = rb = ttk.Button(
            self,
            text=f"{MsgCat.translate('Run')}\n(F5)",
            state="disabled",
            command=self.run,
        )

        # Arguments table
        self.ag = ag = ttk.Labelframe(self, text="Arguments")
        self.at = at = tksheet.Sheet(
            ag,
            headers=[MsgCat.translate("Type"), MsgCat.translate("Value")],
            empty_horizontal=20,
            row_height=25,
            data=self.__args,
            paste_insert_column_limit=True,
            show_top_left=False,
        )
        if parent.style.theme_use() == DARK_THEME:
            at.change_theme("dark blue")
        at.bind(
            "<<ThemeChanged>>",
            lambda _: at.change_theme("dark blue")
            if parent.style.theme_use() == DARK_THEME
            else at.change_theme(),
        )
        at.extra_bindings("end_edit_cell", self.table_end_edit_cell)
        at.extra_bindings("end_insert_rows", self.table_end_insert_rows)
        at.extra_bindings("end_paste", self.table_end_paste)
        at.readonly_columns(columns=[0])
        at.default_row_height(height=30)
        at.column_width(1, width=250)
        if rows_to_add > 0:
            for row_index in range(rows_to_add):
                at.insert_row()
                self.table_end_insert_rows(row=row_index)

        if self.__is_windows:
            cc.grid(sticky="ew", padx=5, pady=5)
        rc.grid(sticky="ew", padx=5, pady=5)
        at.grid(sticky="nsew", padx=5, pady=5)

        if self.__is_windows:
            cg.grid(row=0, column=0, sticky="ew", padx=5)
            rg.grid(row=0, column=1, sticky="ew")
            rb.grid(row=0, column=2, padx=5)
        else:
            rg.grid(row=0, column=0, sticky="ew", padx=5)
            rb.grid(row=0, column=1, padx=5)
        ag.grid(row=1, columnspan=3, sticky="nsew", padx=5, pady=5)

        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        if self.__is_windows:
            self.columnconfigure(1, weight=1)

        if self.__is_windows:
            cg.columnconfigure(0, weight=1)
        rg.columnconfigure(0, weight=1)
        ag.rowconfigure(0, weight=1)
        ag.columnconfigure(0, weight=1)

        self.event_add("<<ToggleFunctionFrame>>", "None")
        self.bind_all(
            "<<ToggleFunctionFrame>>", lambda event: self.set_state(event.state == 1)
        )

    def table_end_insert_rows(self, event: NamedTuple = None, row: int = None):
        if event is not None:
            param1 = event[1]
        else:
            param1 = row
        self.at.create_dropdown(
            r=param1,
            c=0,
            set_value="uint32_t",
            values=PARAMETER_TYPES,
            redraw=True,
            selection_function=self.table_dropdown_change,
        )
        self.at.set_cell_data(r=param1, c=1, value="0")

    def table_end_edit_cell(self, event: NamedTuple):
        row, col, action, text, *_ = event
        if action != "Escape":
            if col == 1:
                self.table_validate(row, text)
            else:
                self.at.dehighlight_cells(row, 1)

    def table_end_paste(self, event: NamedTuple):
        _, (x, y), content = event
        if isinstance(x, int):
            row, col = x, y
            if col == 1:
                text = content[0][0]
                self.table_validate(row, text)
        elif isinstance(x, str):
            what, which = x, y
            if what == "column" and which == 1:
                for idx, field in enumerate(content):
                    # Idk why field is a list itself
                    self.table_validate(idx, field[0])

    def table_validate(self, row: int, text: str):
        t = self.at.get_cell_data(row, 0)
        try:
            # bool & void have readonly cells, no need to validate
            if t in ("float", "double"):
                float(text)
            elif t not in ("char", "char*", "wchar_t", "wchar_t*"):
                int(text)
        # Catch multiple exceptions: https://stackoverflow.com/a/6470452
        except (TypeError, ValueError):
            self.at.highlight_cells(row, 1, bg="red")
        else:
            self.at.dehighlight_cells(row, 1)

    def set_state(self, activate: bool = True):
        if activate:
            self.rc.configure(state="readonly")
            if self.__is_windows:
                self.cc.configure(state="readonly")
            self.rb.configure(state="normal")
            self.at.enable_bindings()
            for binding in ("rc_insert_column", "rc_delete_column", "cut", "delete"):
                self.at.disable_bindings(binding)
            self.bind_run_button()
        else:
            for w in (self.rc, self.rb):
                w.configure(state="disabled")
            if self.__is_windows:
                self.cc.configure(state="disabled")
            self.at.disable_bindings()
            self.unbind_run_button()

    def table_dropdown_change(self, event):
        # pylint: disable=no-else-return
        # pylint: disable=bare-except

        row, _, _, type_ = event
        t = self.at

        if type_ == "bool":
            # Check if type is not bool already
            if t.get_dropdown_value(row, 0) != "bool":
                t.create_dropdown(row, 1, values=["True", "False"], redraw=True)
                t.readonly_cells(row, 1)
            return
        else:
            try:
                t.readonly_cells(row, 1, readonly=False)
                t.delete_dropdown(row, 1)
            except KeyError:
                t.set_cell_data(row, 1)

        if type_ == "void":
            t.set_cell_data(row, 1, value="NULL")
            t.readonly_cells(row, 1)
            return
        else:
            t.readonly_cells(row, 1, readonly=False)

        if type_ in ("float", "double"):
            t.set_cell_data(row, 1, value="0.0")
        elif type_ not in ("char", "char*", "void*", "wchar_t", "wchar_t*"):
            t.set_cell_data(row, 1, value="0")

    def process_queue(self):
        try:
            exc: Exception = self.__exc_q.get_nowait()
        except queue.Empty:
            pass
        else:
            log.exception(exc)
            raise exc

        try:
            result: RunResult = self.__res_q.get_nowait()
        except queue.Empty:
            self.after(100, self.process_queue)
        else:
            self.event_generate("<<OutputSuccess>>", when="tail")
            self.__status.set("Operation successful")
            ret = Marshaller.pytype2str(result.ret)
            self.__output.set(ret)
            if self.__is_outmode.get():
                self.at.set_column_data(1, result.values, redraw=True)
            self.activate_copy_button()
            self.rb.configure(state="normal")

    def run(self, *_):
        def handle_exc(e: Exception, status: str):
            log.exception(e)
            self.__exc_type.set(type(e).__name__)
            # ! Cannot pass an arbitrary string directly even though Tk supports it
            # https://stackoverflow.com/a/21234342
            # https://bugs.python.org/issue3405
            self.event_generate("<<OutputException>>")
            self.__output.set(str(e))
            self.__status.set(status)
            self.activate_copy_button(bootstyle="danger")
            self.rb.configure(state="normal")

        ret_type = self.__returns.get()
        self.__status.set("Running...")
        self.rb.configure(state="disabled")
        self.unbind_run_button()

        try:
            thread = Runner(
                self.__exc_q,
                self.__res_q,
                self.__args,
                self.__call_conv.get(),
                ret_type,
                self.__lib_path.get(),
                self.__export.get(),
            )
        except Exception as e:  # pylint: disable=broad-except
            handle_exc(e, "Invalid argument(s)")
            self.bind_run_button()
            return
        self.__is_running.set(True)
        thread.start()

        try:
            self.process_queue()
        except Exception as e:  # pylint: disable=broad-except
            handle_exc(e, "An error occured")
        self.__is_running.set(False)
        self.bind_run_button()

    # * Helpers
    def activate_copy_button(self, state="normal", bootstyle="default"):
        self.__parent.output.oc.configure(state=state, bootstyle=bootstyle)

    def bind_run_button(self):
        # pylint: disable=attribute-defined-outside-init
        log.debug("Run button binded to F5")
        self.rb.bind_all("<F5>", self.run)

    def unbind_run_button(self):
        log.debug("Run button unbinded")
        self.rb.unbind_all("<F5>")
