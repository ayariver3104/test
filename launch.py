lll
# Recreate and show the launcher.py content as plain text (and save it again for convenience).
from textwrap import dedent
from pathlib import Path

code = dedent(r'''
    import os
    import sys
    import json
    import shlex
    import platform
    import subprocess
    from dataclasses import dataclass, field
    from typing import List, Dict, Optional, Any, Tuple, Set
    
    import flet as ft
    
    ###############################################################################
    # Data models
    ###############################################################################
    @dataclass
    class AppItem:
        id: str
        name: str
        command: str
        args: List[str] = field(default_factory=list)
        cwd: Optional[str] = None
        icon: Optional[str] = None
        tags: List[str] = field(default_factory=list)
        env: Dict[str, str] = field(default_factory=dict)
        run_as_admin: bool = False
        favorite: bool = False
        notes: Optional[str] = None
    
    @dataclass
    class Profile:
        id: str
        name: str
        steps: List[Dict[str, Any]]  # [{"app": "db", "delay_ms": 500}, ...]
        parallel: bool = False
    
    @dataclass
    class AppConfig:
        version: int
        apps: List[AppItem]
        profiles: List[Profile] = field(default_factory=list)
        ui: Dict[str, Any] = field(default_factory=lambda: {"default_view": "list", "theme": "auto"})
    
    
    ###############################################################################
    # Config loading
    ###############################################################################
    def load_config(path: str) -> AppConfig:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        apps: List[AppItem] = []
        for a in raw.get("apps", []):
            item = AppItem(
                id=a.get("id") or a.get("name"),
                name=a.get("name", ""),
                command=a.get("command", ""),
                args=a.get("args", []) if isinstance(a.get("args", []), list) else shlex.split(a.get("args", "")),
                cwd=a.get("cwd"),
                icon=a.get("icon"),
                tags=a.get("tags", []) or [],
                env=a.get("env", {}) or {},
                run_as_admin=bool(a.get("run_as_admin", False)),
                favorite=bool(a.get("favorite", False)),
                notes=a.get("notes"),
            )
            apps.append(item)
    
        profiles: List[Profile] = []
        for p in raw.get("profiles", []):
            profiles.append(
                Profile(
                    id=p.get("id") or p.get("name"),
                    name=p.get("name", ""),
                    steps=p.get("steps", []),
                    parallel=bool(p.get("parallel", False)),
                )
            )
        ui = raw.get("ui", {"default_view": "list", "theme": "auto"})
        return AppConfig(version=raw.get("version", 1), apps=apps, profiles=profiles, ui=ui)
    
    
    ###############################################################################
    # Process utilities
    ###############################################################################
    def _merge_env(custom: Dict[str, str]) -> Dict[str, str]:
        env = os.environ.copy()
        env.update({k: str(v) for k, v in (custom or {}).items()})
        return env
    
    def _open_folder(path: str):
        if not path:
            return
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    
    def _initials(text: str) -> str:
        s = "".join(ch for ch in text if ch.isalnum())
        if not s:
            return "?"
        return (s[0] + (s[1] if len(s) > 1 else "")).upper()
    
    def _run_as_admin_windows(exe: str, params: List[str], cwd: Optional[str]):
        # Works best for .exe; batch/scripts may need wrapping.
        import ctypes
        from subprocess import list2cmdline
        param_str = list2cmdline(params or [])
        SW_SHOWNORMAL = 1
        # Returns >32 on success
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, param_str, cwd or None, SW_SHOWNORMAL)
        if ret <= 32:
            raise RuntimeError(f"Elevation failed with code {ret}")
    
    def launch_app(item: AppItem, extra_args: Optional[List[str]] = None) -> Tuple[bool, str]:
        args = item.args.copy()
        if extra_args:
            args += extra_args
        env = _merge_env(item.env)
        try:
            if sys.platform == "win32" and item.run_as_admin:
                # For .exe; for .bat consider wrapping via powershell Start-Process -Verb RunAs
                if item.command.lower().endswith(".exe"):
                    _run_as_admin_windows(item.command, args, item.cwd)
                    return True, "起動（管理者）を要求しました。"
                else:
                    # Fallback: best-effort normal launch with note
                    p = subprocess.Popen([item.command] + args, cwd=item.cwd or None, env=env, creationflags=subprocess.CREATE_NEW_CONSOLE)  # type: ignore
                    return True, "管理者権限はスクリプトに未対応のため通常起動しました。"
            else:
                if sys.platform == "win32":
                    p = subprocess.Popen([item.command] + args, cwd=item.cwd or None, env=env, creationflags=subprocess.CREATE_NEW_CONSOLE)  # type: ignore
                else:
                    p = subprocess.Popen([item.command] + args, cwd=item.cwd or None, env=env)
                return True, "起動しました。"
        except FileNotFoundError:
            return False, "コマンドまたはパスが見つかりません。設定を確認してください。"
        except Exception as e:
            return False, f"起動に失敗: {e}"
    
    
    ###############################################################################
    # UI
    ###############################################################################
    class LauncherApp(ft.UserControl):
        def __init__(self, config_path: str):
            super().__init__()
            self.config_path = config_path
            self.cfg: AppConfig = load_config(config_path)
            self.view_mode: str = self.cfg.ui.get("default_view", "list")  # "list" | "grid"
            self.search_query: str = ""
            self.active_tags: Set[str] = set()
            self.tag_universe: List[str] = sorted({t for a in self.cfg.apps for t in (a.tags or [])})
    
        def build(self):
            # Top bar
            self.search = ft.TextField(
                hint_text="Search apps… (name / tag / notes / command)",
                dense=True,
                on_change=self._on_search_change,
                prefix_icon=ft.icons.SEARCH,
                expand=True,
            )
    
            self.reload_btn = ft.IconButton(ft.icons.REFRESH, tooltip="Reload config", on_click=self._on_reload)
            self.toggle_view_btn = ft.IconButton(ft.icons.GRID_VIEW if self.view_mode == "list" else ft.icons.TABLE_ROWS,
                                                 tooltip="Toggle List / Grid",
                                                 on_click=self._on_toggle_view)
            self.start_all_btn = ft.FilledButton(text="Start All (Filtered)", icon=ft.icons.PLAY_ARROW, on_click=self._on_start_all)
    
            top_row = ft.Row([self.search, self.start_all_btn, self.reload_btn, self.toggle_view_btn], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
    
            # Tag filters
            chips = []
            for tag in self.tag_universe:
                chips.append(
                    ft.FilterChip(
                        label=ft.Text(tag),
                        selected=False,
                        on_selected=self._on_tag_toggled(tag),
                    )
                )
            self.tag_row = ft.Wrap(chips, spacing=8, run_spacing=8)
    
            # Content area
            self.content = ft.Container(expand=True)
            self._refresh_content()
    
            return ft.Column(
                controls=[top_row, self.tag_row, ft.Divider(), self.content],
                expand=True,
                spacing=8,
            )
    
        # Event handlers
        def _on_search_change(self, e: ft.ControlEvent):
            self.search_query = self.search.value.strip().lower()
            self._refresh_content()
    
        def _on_tag_toggled(self, tag: str):
            def handler(e: ft.ControlEvent):
                chip: ft.FilterChip = e.control  # type: ignore
                if chip.selected:
                    self.active_tags.add(tag)
                else:
                    self.active_tags.discard(tag)
                self._refresh_content()
            return handler
    
        def _on_toggle_view(self, e: ft.ControlEvent):
            self.view_mode = "grid" if self.view_mode == "list" else "list"
            self.toggle_view_btn.icon = ft.icons.GRID_VIEW if self.view_mode == "list" else ft.icons.TABLE_ROWS
            self._refresh_content()
    
        def _on_reload(self, e: ft.ControlEvent):
            try:
                self.cfg = load_config(self.config_path)
                self.tag_universe = sorted({t for a in self.cfg.apps for t in (a.tags or [])})
                # Rebuild chips
                self.tag_row.controls.clear()
                for tag in self.tag_universe:
                    self.tag_row.controls.append(
                        ft.FilterChip(label=ft.Text(tag), selected=(tag in self.active_tags), on_selected=self._on_tag_toggled(tag))
                    )
                self.update()
                self._toast("設定を再読み込みしました。")
            except Exception as ex:
                self._dialog("読み込みエラー", f"{ex}")
    
        def _on_start_all(self, e: ft.ControlEvent):
            items = self._filtered_items()
            if not items:
                self._toast("該当するアプリがありません。")
                return
            failures = 0
            for it in items:
                ok, msg = launch_app(it)
                if not ok:
                    failures += 1
            if failures:
                self._dialog("一括起動", f"{len(items)}件中 {failures}件で失敗しました。")
            else:
                self._toast(f"{len(items)}件を起動しました。")
    
        # Rendering
        def _filtered_items(self) -> List[AppItem]:
            q = self.search_query
            tags = self.active_tags
            out: List[AppItem] = []
            for a in self.cfg.apps:
                if tags and not (tags.intersection(set(a.tags or []))):
                    continue
                if q:
                    hay = " ".join([a.name, " ".join(a.tags or []), a.notes or "", a.command]).lower()
                    if q not in hay:
                        continue
                out.append(a)
            # Sort favorites first, then name
            out.sort(key=lambda x: ((not x.favorite), x.name.lower()))
            return out
    
        def _avatar(self, a: AppItem, size: int = 40):
            if a.icon and os.path.exists(a.icon):
                return ft.Image(src=a.icon, width=size, height=size, fit=ft.ImageFit.COVER, repeat=ft.ImageRepeat.NO_REPEAT)
            return ft.CircleAvatar(content=ft.Text(_initials(a.name)), width=size, height=size)
    
        def _tag_chips(self, a: AppItem) -> ft.Wrap:
            return ft.Wrap([ft.Chip(label=ft.Text(t)) for t in (a.tags or [])], spacing=6, run_spacing=6)
    
        def _row_controls(self, a: AppItem) -> ft.Row:
            run_btn = ft.FilledButton("起動", icon=ft.icons.PLAY_ARROW, on_click=lambda e: self._run_item(a))
            folder_btn = ft.IconButton(ft.icons.FOLDER_OPEN, tooltip="作業フォルダを開く", on_click=lambda e: _open_folder(a.cwd or os.path.dirname(a.command or "") or "."))
            more_btn = ft.PopupMenuButton(items=[
                ft.PopupMenuItem(text="コマンドをコピー", on_click=lambda e: self._copy_cmd(a)),
                ft.PopupMenuItem(text="管理者として実行" + ("" if sys.platform == "win32" else "（Windowsのみ）"), on_click=lambda e: self._run_item(a, as_admin=True)),
                ft.PopupMenuItem(),  # divider
                ft.PopupMenuItem(text="設定ファイルを開く", on_click=lambda e: _open_folder(os.path.dirname(self.config_path))),
            ])
            return ft.Row([run_btn, folder_btn, more_btn], alignment=ft.MainAxisAlignment.END, spacing=6)
    
        def _list_view(self, items: List[AppItem]) -> ft.ListView:
            lv = ft.ListView(expand=True, spacing=8, padding=0, auto_scroll=False)
            for a in items:
                row = ft.Container(
                    content=ft.Row(
                        controls=[
                            self._avatar(a, size=40),
                            ft.Column([
                                ft.Row([ft.Text(a.name, weight=ft.FontWeight.W_600), ft.Icon(ft.icons.STAR, color=ft.colors.AMBER, visible=a.favorite)]),
                                ft.Text(a.notes or a.command, size=12, color=ft.colors.ON_SURFACE_VARIANT),
                                self._tag_chips(a)
                            ], expand=True, spacing=3),
                            self._row_controls(a),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    padding=10,
                    border_radius=8,
                    bgcolor=ft.colors.SURFACE_CONTAINER_HIGHEST,
                )
                lv.controls.append(row)
            return lv
    
        def _grid_view(self, items: List[AppItem]) -> ft.GridView:
            gv = ft.GridView(expand=True, runs_count=4, max_extent=350, child_aspect_ratio=1.9, spacing=10, run_spacing=10)
            for a in items:
                card = ft.Container(
                    padding=12,
                    border_radius=12,
                    bgcolor=ft.colors.SURFACE_CONTAINER_HIGHEST,
                    content=ft.Column([
                        ft.Row([self._avatar(a, size=48), ft.Text(a.name, weight=ft.FontWeight.W_600)], alignment=ft.MainAxisAlignment.START, spacing=12),
                        ft.Text(a.notes or a.command, size=12, color=ft.colors.ON_SURFACE_VARIANT, no_wrap=True),
                        self._tag_chips(a),
                        ft.Row([
                            ft.FilledButton("起動", icon=ft.icons.PLAY_ARROW, on_click=lambda e, app=a: self._run_item(app)),
                            ft.IconButton(ft.icons.FOLDER_OPEN, tooltip="作業フォルダを開く", on_click=lambda e, app=a: _open_folder(app.cwd or os.path.dirname(app.command or "") or ".")),
                            ft.IconButton(ft.icons.MORE_VERT, tooltip="詳細", on_click=lambda e, app=a: self._details(app)),
                        ], alignment=ft.MainAxisAlignment.END, spacing=6)
                    ], spacing=8)
                )
                gv.controls.append(card)
            return gv
    
        def _refresh_content(self):
            items = self._filtered_items()
            if self.view_mode == "list":
                self.content.content = self._list_view(items)
            else:
                self.content.content = self._grid_view(items)
            self.update()
    
        # Actions
        def _run_item(self, a: AppItem, as_admin: bool = False):
            if as_admin:
                a = AppItem(**{**a.__dict__, "run_as_admin": True})
            ok, msg = launch_app(a)
            if ok:
                self._toast(f"{a.name}: {msg}")
            else:
                self._dialog(f"{a.name}: エラー", msg)
    
        def _copy_cmd(self, a: AppItem):
            cmd = " ".join([a.command] + a.args)
            self.page.set_clipboard(cmd)
            self._toast("コマンドをコピーしました。")
    
        def _details(self, a: AppItem):
            body = ft.Column([
                ft.Text(a.name, size=18, weight=ft.FontWeight.W_600),
                ft.Text(f"Command: {a.command} {' '.join(a.args)}", selectable=True),
                ft.Text(f"CWD: {a.cwd or '-'}"),
                ft.Text(f"Tags: {', '.join(a.tags) or '-'}"),
                ft.Text(f"Admin: {'Yes' if a.run_as_admin else 'No'}"),
                ft.Text(f"Notes: {a.notes or '-'}"),
            ], tight=True, spacing=6)
            dlg = ft.AlertDialog(title=ft.Text("アプリ詳細"), content=body, actions=[ft.TextButton("閉じる", on_click=lambda e: self.page.close(dlg))])
            self.page.open(dlg)
    
        # Lightweight toasts/dialogs that avoid version-specific SnackBar pitfalls
        def _toast(self, message: str):
            try:
                # Prefer Snackbar if available
                sb = ft.SnackBar(ft.Text(message), open=True, show_close_icon=True)
                self.page.open(sb)
            except Exception:
                # Fallback to banner-like dialog
                dlg = ft.AlertDialog(title=ft.Text(message), on_dismiss=lambda e: None)
                self.page.open(dlg)
    
        def _dialog(self, title: str, message: str):
            dlg = ft.AlertDialog(title=ft.Text(title), content=ft.Text(message), actions=[ft.TextButton("OK", on_click=lambda e: self.page.close(dlg))])
            self.page.open(dlg)
    
    
    ###############################################################################
    # Entry point
    ###############################################################################
    def main(page: ft.Page):
        page.title = "Launcher"
        page.theme_mode = ft.ThemeMode.SYSTEM
        page.padding = 12
        page.window_min_width = 720
        page.window_min_height = 520
    
        cfg_path = "apps.json"
        if len(sys.argv) > 1:
            cfg_path = sys.argv[1]
        if not os.path.exists(cfg_path):
            page.add(ft.Text(f"設定ファイルが見つかりません: {cfg_path}"))
            return
    
        app = LauncherApp(cfg_path)
        page.add(app)
    
    if __name__ == "__main__":
        ft.app(target=main)
''')

# Save again for convenience
outdir = Path("/mnt/data/flet_launcher")
outdir.mkdir(parents=True, exist_ok=True)
(outdir / "launcher.py").write_text(code, encoding="utf-8")

print(code)