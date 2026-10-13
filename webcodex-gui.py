#!/usr/bin/env python3
"""Local project picker for a WebCodex Runtime installation.

The browser cannot obtain an absolute local directory path from a folder input.
This small GTK host uses the operating system's folder picker, then delegates
registration to the installed WebCodex CLI. No HTTP endpoint is added.
"""

import json
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.0")
from gi.repository import Gio, GLib, Gtk, WebKit2

import webcodex_tunnel_settings as tunnel_settings


BASE = Path("/home/qyw/WebCodex")
CLI = BASE / "installed/bin/webcodex"
ENVIRONMENT = BASE / "installed/environment"
RUNTIME_URL = "http://127.0.0.1:8080/runtime"


def run_command(*args):
    return subprocess.run(
        [str(CLI), *args, "--environment-dir", str(ENVIRONMENT)],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )


class WebCodexWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="WebCodex")
        self.set_default_size(1180, 780)
        self.set_size_request(780, 500)
        self.set_icon_from_file(str(BASE / "icon.png"))
        self._busy = False

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(outer)

        header = Gtk.HeaderBar(title="WebCodex")
        header.set_show_close_button(True)
        self.set_titlebar(header)
        self.add_button = Gtk.Button(label="选择文件夹添加项目")
        self.add_button.connect("clicked", self.choose_folder)
        header.pack_start(self.add_button)
        settings_button = Gtk.Button(label="Tunnel 设置")
        settings_button.connect("clicked", self.show_tunnel_settings)
        header.pack_end(settings_button)
        refresh_button = Gtk.Button(label="刷新")
        refresh_button.connect("clicked", lambda *_: self.refresh())
        header.pack_end(refresh_button)

        panes = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        outer.pack_start(panes, True, True, 0)
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        side.set_border_width(14)
        panes.pack1(side, resize=False, shrink=False)
        panes.set_position(300)
        title = Gtk.Label(label="已添加的项目")
        title.set_xalign(0)
        side.pack_start(title, False, False, 0)
        self.projects = Gtk.ListBox()
        self.projects.set_selection_mode(Gtk.SelectionMode.NONE)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(self.projects)
        side.pack_start(scroller, True, True, 0)
        self.side_status = Gtk.Label(label="正在读取项目…")
        self.side_status.set_xalign(0)
        self.side_status.set_line_wrap(True)
        side.pack_start(self.side_status, False, False, 0)

        browser = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        panes.pack2(browser, resize=True, shrink=False)
        browser_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        browser_bar.set_border_width(8)
        browser.pack_start(browser_bar, False, False, 0)
        browser_title = Gtk.Label(label="WebCodex Runtime")
        browser_title.set_xalign(0)
        browser_bar.pack_start(browser_title, True, True, 0)
        open_button = Gtk.Button(label="在浏览器打开")
        open_button.connect("clicked", self.open_runtime_in_browser)
        browser_bar.pack_end(open_button, False, False, 0)
        reload_button = Gtk.Button(label="刷新页面")
        reload_button.connect("clicked", lambda *_: self.web.reload())
        browser_bar.pack_end(reload_button, False, False, 0)
        self.page_status = Gtk.Label(label="正在加载浏览器界面…")
        self.page_status.set_xalign(0)
        self.page_status.set_margin_start(8)
        browser.pack_start(self.page_status, False, False, 0)
        self.page_failed = False
        # WebKit follows the desktop's proxy settings even for loopback. The
        # local Runtime must connect directly or a proxy can return a blank
        # 502 page while the Server itself is healthy.
        WebKit2.WebContext.get_default().set_network_proxy_settings(
            WebKit2.NetworkProxyMode.NO_PROXY, None
        )
        self.content_manager = WebKit2.UserContentManager()
        self.initial_access_script = False
        credential_path = ENVIRONMENT / "webcodex-user-token"
        try:
            credential = credential_path.read_text().strip()
        except OSError:
            credential = ""
        if credential:
            script = (
                "if (location.origin === 'http://127.0.0.1:8080' "
                "&& location.pathname.startsWith('/runtime')) {"
                "try {"
                "sessionStorage.setItem('webcodex.runtime.credential.v1', "
                + json.dumps(credential)
                + ");"
                "localStorage.setItem('webcodex.runtime.v2.view.v1', 'projects');"
                "} catch (_) {}"
                "}"
            )
            self.content_manager.add_script(WebKit2.UserScript.new(
                script,
                WebKit2.UserContentInjectedFrames.TOP_FRAME,
                WebKit2.UserScriptInjectionTime.START,
                None,
                None,
            ))
            self.initial_access_script = True
        self.web = WebKit2.WebView.new_with_user_content_manager(self.content_manager)
        self.web.connect("load-changed", self.page_load_changed)
        self.web.connect("load-failed", self.page_load_failed)
        browser.pack_start(self.web, True, True, 0)

        self.status = Gtk.Label(label="正在连接本机服务…")
        self.status.set_xalign(0)
        self.status.set_margin_start(14)
        self.status.set_margin_top(8)
        self.status.set_margin_bottom(8)
        outer.pack_end(self.status, False, False, 0)
        self.connect("destroy", Gtk.main_quit)
        self.refresh()

    def set_busy(self, value):
        self._busy = value
        self.add_button.set_sensitive(not value)

    def inform(self, message, error=False):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.ERROR if error else Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.CLOSE,
            text=message,
        )
        dialog.run()
        dialog.destroy()

    def page_load_changed(self, _web, event):
        if event == WebKit2.LoadEvent.STARTED:
            self.page_failed = False
            self.page_status.set_text("正在加载 WebCodex Runtime…")
        elif event == WebKit2.LoadEvent.FINISHED and not self.page_failed:
            response = self.web.get_main_resource().get_response()
            if response and response.get_status_code() != 200:
                self.page_failed = True
                self.page_status.set_text(
                    f"Runtime 页面加载失败：HTTP {response.get_status_code()}。请点击刷新页面。"
                )
                return
            if self.initial_access_script:
                # The initial local sign-in should not silently undo a later
                # explicit lock/logout when the user reloads the page.
                self.content_manager.remove_all_scripts()
                self.initial_access_script = False
            self.page_status.set_text("WebCodex Runtime · http://127.0.0.1:8080/runtime")

    def page_load_failed(self, _web, _event, _uri, error):
        self.page_failed = True
        self.page_status.set_text(f"页面暂时无法加载：{error.message}")
        return False

    def open_runtime_in_browser(self, *_):
        try:
            Gio.AppInfo.launch_default_for_uri(RUNTIME_URL, None)
        except GLib.Error as exc:
            self.inform(f"无法打开浏览器：{exc.message}", error=True)

    def show_tunnel_settings(self, *_):
        try:
            current_id, current_key = tunnel_settings.current_credentials()
        except (OSError, ValueError) as exc:
            self.inform(f"无法读取 Tunnel 设置：{exc}", error=True)
            return

        dialog = Gtk.Dialog(title="OpenAI Secure Tunnel 设置", transient_for=self, modal=True)
        dialog.set_default_size(550, 300)
        dialog.add_button("关闭", Gtk.ResponseType.CANCEL)
        save_button = dialog.add_button("保存并检查连接", Gtk.ResponseType.OK)
        content = dialog.get_content_area()
        content.set_border_width(16)
        grid = Gtk.Grid(column_spacing=12, row_spacing=12)
        content.pack_start(grid, True, True, 0)

        id_label = Gtk.Label(label="Tunnel ID")
        id_label.set_xalign(0)
        grid.attach(id_label, 0, 0, 1, 1)
        id_entry = Gtk.Entry()
        id_entry.set_text(current_id)
        id_entry.set_width_chars(42)
        grid.attach(id_entry, 1, 0, 1, 1)

        key_label = Gtk.Label(label="API key")
        key_label.set_xalign(0)
        grid.attach(key_label, 0, 1, 1, 1)
        key_entry = Gtk.Entry()
        key_entry.set_text(current_key)
        key_entry.set_visibility(False)
        key_entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        grid.attach(key_entry, 1, 1, 1, 1)
        reveal = Gtk.CheckButton(label="显示 API key")
        reveal.connect("toggled", lambda button: key_entry.set_visibility(button.get_active()))
        grid.attach(reveal, 1, 2, 1, 1)

        status_label = Gtk.Label(label="正在检查 Tunnel 状态…")
        status_label.set_xalign(0)
        status_label.set_line_wrap(True)
        grid.attach(status_label, 0, 3, 2, 1)
        note = Gtk.Label(label="修改现有凭据会短暂断开 ChatGPT。新连接未就绪时会恢复原配置。")
        note.set_xalign(0)
        note.set_line_wrap(True)
        grid.attach(note, 0, 4, 2, 1)

        busy = [False]

        def finish(message, ok):
            busy[0] = False
            if not dialog.get_visible():
                return False
            dialog.set_deletable(True)
            save_button.set_sensitive(True)
            status_label.set_text(message)
            if ok:
                dialog.destroy()
                self.inform(message)
            return False

        def start_recovery(_button):
            if busy[0]:
                return
            busy[0] = True
            save_button.set_sensitive(False)
            status_label.set_text("正在恢复原 Tunnel 配置…")

            def work():
                try:
                    tunnel_settings.recover_backup()
                    GLib.idle_add(finish, "原 Tunnel 配置已恢复并就绪", True)
                except Exception:
                    GLib.idle_add(finish, "恢复失败；原配置仍保存在私有备份中", False)

            threading.Thread(target=work, daemon=True).start()

        if tunnel_settings.BACKUP_FILE.exists():
            recovery = Gtk.Button(label="恢复上次配置")
            recovery.connect("clicked", start_recovery)
            grid.attach(recovery, 1, 5, 1, 1)

        def response(_dialog, response_id):
            if busy[0]:
                return
            if response_id != Gtk.ResponseType.OK:
                dialog.destroy()
                return
            new_id = id_entry.get_text().strip()
            new_key = key_entry.get_text()
            if (new_id, new_key) == (current_id, current_key):
                dialog.destroy()
                return
            confirmation = Gtk.MessageDialog(
                transient_for=dialog,
                modal=True,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.NONE,
                text="保存新的 Tunnel 设置？",
            )
            confirmation.format_secondary_text(
                "这会短暂重启 Tunnel。若更换 Tunnel ID，ChatGPT 连接器也需选择新的 ID。"
            )
            confirmation.add_buttons("取消", Gtk.ResponseType.CANCEL, "保存并重启", Gtk.ResponseType.OK)
            accepted = confirmation.run() == Gtk.ResponseType.OK
            confirmation.destroy()
            if not accepted:
                return
            busy[0] = True
            dialog.set_deletable(False)
            save_button.set_sensitive(False)
            status_label.set_text("正在保存并检查 Tunnel…")

            def work():
                try:
                    result = tunnel_settings.save_credentials(new_id, new_key)
                    GLib.idle_add(finish, result, True)
                except (OSError, ValueError, RuntimeError) as exc:
                    GLib.idle_add(finish, str(exc), False)

            threading.Thread(target=work, daemon=True).start()

        dialog.connect("response", response)
        dialog.show_all()

        def read_status():
            message = tunnel_settings.status()
            GLib.idle_add(lambda: status_label.set_text(message) if dialog.get_visible() and not busy[0] else False)

        threading.Thread(target=read_status, daemon=True).start()

    def refresh(self):
        def work():
            try:
                subprocess.run(
                    ["systemctl", "--user", "start", "webcodex.service", "webcodex-runner-1000.service"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=True,
                )
                for _ in range(30):
                    try:
                        urllib.request.urlopen("http://127.0.0.1:8080/healthz", timeout=2).close()
                        break
                    except (urllib.error.URLError, TimeoutError):
                        time.sleep(0.2)
                result = run_command("environment", "status", "--json")
                if result.returncode:
                    raise RuntimeError(result.stderr.strip() or "无法获取项目状态")
                observation = json.loads(result.stdout)["observation"]
                # The saved local environment owns exact paths. The observed
                # project list contains IDs, never browser-supplied paths.
                saved = json.loads((ENVIRONMENT / "environment.json").read_text())
                paths = [item["path"] for item in saved.get("projects", []) if item.get("path")]
                GLib.idle_add(self.show_projects, paths, observation)
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
                GLib.idle_add(self.show_error, str(exc))

        threading.Thread(target=work, daemon=True).start()

    def show_projects(self, paths, observation):
        for child in self.projects.get_children():
            self.projects.remove(child)
        for path in paths:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label=path)
            label.set_xalign(0)
            label.set_line_wrap(True)
            label.set_max_width_chars(34)
            label.set_margin_top(8)
            label.set_margin_bottom(8)
            row.add(label)
            self.projects.add(row)
        self.projects.show_all()
        self.side_status.set_text(f"{len(paths)} 个项目" if paths else "尚未添加项目")
        ready = observation.get("server_reachable") and observation.get("runner_online")
        self.status.set_text("本机 Server 和 Runner 已就绪" if ready else "本机服务尚未就绪，请刷新")
        if ready:
            self.page_failed = False
            self.web.load_uri(RUNTIME_URL)
        return False

    def show_error(self, message):
        self.status.set_text("无法读取 WebCodex 状态")
        self.side_status.set_text(message)
        return False

    def choose_folder(self, *_):
        if self._busy:
            return
        chooser = Gtk.FileChooserNative.new(
            "选择要添加到 WebCodex 的文件夹",
            self,
            Gtk.FileChooserAction.SELECT_FOLDER,
            "选择",
            "取消",
        )
        response = chooser.run()
        path = chooser.get_filename() if response == Gtk.ResponseType.ACCEPT else None
        chooser.destroy()
        if not path:
            return

        confirm = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,
            text="将此文件夹添加为 WebCodex 项目？",
        )
        confirm.format_secondary_text(
            f"{path}\n\n添加后，连接的 AI 可以在此项目中读取和修改文件，并调用本机开发工具。"
        )
        confirm.add_buttons("取消", Gtk.ResponseType.CANCEL, "添加项目", Gtk.ResponseType.OK)
        accepted = confirm.run() == Gtk.ResponseType.OK
        confirm.destroy()
        if not accepted:
            return

        self.set_busy(True)
        self.status.set_text("正在添加项目…")

        def work():
            try:
                result = run_command("environment", "add-project", path)
                if result.returncode:
                    raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "项目添加失败")
                GLib.idle_add(self.added, path)
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                GLib.idle_add(self.add_failed, str(exc))

        threading.Thread(target=work, daemon=True).start()

    def added(self, path):
        self.set_busy(False)
        self.status.set_text(f"已添加：{path}")
        self.refresh()
        return False

    def add_failed(self, message):
        self.set_busy(False)
        self.status.set_text("项目添加失败")
        self.inform(message, error=True)
        return False


if __name__ == "__main__":
    window = WebCodexWindow()
    window.show_all()
    Gtk.main()
