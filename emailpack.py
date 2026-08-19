"""Ready-to-send email packs (ported from PeerParley, trimmed to link/assignment
emails with no attachments).

* **.eml pack** — one .eml per recipient; opens as a pre-filled draft in Outlook /
  Apple Mail / Thunderbird. Review and press Send.
* **Auto-send pack** — a zip with double-clickable scripts that drive the mail app
  already on the instructor's computer: `Send emails (Windows).cmd` (a launcher for
  `send_all_windows.ps1`, Outlook) or `send_all_mac.applescript` (Outlook / Apple
  Mail). A web app can't drive your desktop mail client, so the work is handed to a
  script that runs on your machine.
"""
from __future__ import annotations

import base64
import io
import re
import zipfile
from email.message import EmailMessage
from typing import Dict, List, Tuple

from . import email_delivery as mail


def _safe(s) -> str:
    return re.sub(r"[^\w]+", "_", str(s)).strip("_") or "student"


def _strip_html(h: str) -> str:
    t = re.sub(r"<br\s*/?>", "\n", h or "")
    t = re.sub(r"</p>", "\n\n", t)
    return re.sub(r"<[^>]+>", "", t).replace("&nbsp;", " ").strip()


def _b64(s: str) -> str:
    return base64.b64encode((s or "").encode("utf-8")).decode("ascii")


def parts_from_messages(messages: List[mail.Message]) -> List[dict]:
    """Transport-neutral parts from already-rendered Message objects."""
    return [{"to": m.to_email, "name": m.to_name, "subject": m.subject,
             "body": m.body, "attachments": []}
            for m in messages if m.to_email]


# --------------------------------------------------------------------------- #
# .eml pack
# --------------------------------------------------------------------------- #
def _eml(part: dict) -> bytes:
    msg = EmailMessage()
    msg["Subject"] = part["subject"]
    msg["To"] = part["to"] or ""
    msg.set_content(_strip_html(part["body"]) or " ")
    msg.add_alternative(part["body"] or "", subtype="html")
    return msg.as_bytes()


def eml_zip(messages: List[mail.Message], folder_label: str = "Emails") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        wrote = False
        for p in parts_from_messages(messages):
            z.writestr(f"{folder_label}/{_safe(p['name'])}.eml", _eml(p))
            wrote = True
        if not wrote:
            z.writestr("README.txt", "No recipients with an email address.")
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Auto-send pack
# --------------------------------------------------------------------------- #
def _ps_sq(s: str) -> str:
    return "'" + (s or "").replace("'", "''") + "'"


def _as_str(s: str) -> str:
    return '"' + ((s or "").replace("\\", "\\\\").replace('"', '\\"')
                  .replace("\r", "").replace("\n", "\\n")) + '"'


def _windows_launcher() -> str:
    return (
        "@echo off\r\n"
        "setlocal\r\n"
        "cd /d \"%~dp0\"\r\n"
        "echo.\r\n"
        "echo   TeamForge - sending your emails through Outlook...\r\n"
        "echo   (If Windows asks, choose \"More info\" then \"Run anyway\".)\r\n"
        "echo.\r\n"
        "powershell -NoProfile -ExecutionPolicy Bypass -File \"%~dp0send_all_windows.ps1\"\r\n"
        "echo.\r\n"
        "echo   All done. You can close this window.\r\n"
        "pause\r\n")


def _powershell(parts: List[dict]) -> str:
    rows = []
    for p in parts:
        rows.append("  @{ to=%s; subject=%s; body64=%s }" % (
            _ps_sq(p["to"]), _ps_sq(p["subject"]), _ps_sq(_b64(p["body"]))))
    return (
        "# TeamForge - email engine (Outlook). Don't run this directly:\n"
        "# double-click 'Send emails (Windows).cmd' in this folder instead.\n"
        "# Outlook must be installed and signed in. Sends from your account.\n"
        "$ErrorActionPreference = 'Stop'\n"
        "try {\n"
        "  $outlook = New-Object -ComObject Outlook.Application\n"
        "} catch {\n"
        "  Write-Host 'Could not start Outlook. Make sure it is installed and signed in.' "
        "-ForegroundColor Yellow\n"
        "  return\n"
        "}\n"
        "$msgs = @(\n" + ",\n".join(rows) + "\n)\n"
        "$sent = 0; $skipped = 0\n"
        "foreach ($m in $msgs) {\n"
        "  if (-not $m.to) { $skipped++; continue }\n"
        "  try {\n"
        "    $mail = $outlook.CreateItem(0)\n"
        "    $mail.To = $m.to\n"
        "    $mail.Subject = $m.subject\n"
        "    $mail.HTMLBody = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($m.body64))\n"
        "    $mail.Send(); $sent++\n"
        "    Write-Host \"  sent -> $($m.to)\"\n"
        "  } catch {\n"
        "    Write-Host \"  could not send to $($m.to): $($_.Exception.Message)\" "
        "-ForegroundColor Yellow\n"
        "  }\n"
        "}\n"
        "Write-Host \"\"\n"
        "Write-Host \"Sent $sent message(s) via Outlook.\" -ForegroundColor Green\n"
        "if ($skipped) { Write-Host \"$skipped had no email address and were skipped.\" }\n")


def _applescript(parts: List[dict]) -> str:
    lines = [
        '-- TeamForge - send every email via your Mac mail app.',
        '-- Double-click to open in Script Editor, then click Run (the > button).',
        '-- Pick your mail app when asked (Microsoft Outlook is the default).',
        '-- Approve the one-time control prompt. Sends from your account.',
        '',
        'set msgs to {}',
    ]
    for p in parts:
        lines.append("set end of msgs to {|to|:%s, |subj|:%s, |body|:%s}" % (
            _as_str(p["to"]), _as_str(p["subject"]), _as_str(_strip_html(p["body"]))))
    lines += [
        'set appPick to (choose from list {"Microsoft Outlook", "Apple Mail"} '
        'with prompt "Send all of these using which mail app?" '
        'default items {"Microsoft Outlook"})',
        'if appPick is false then return',
        'set appPick to item 1 of appPick',
        'set sentCount to 0',
        'if appPick is "Microsoft Outlook" then',
        '  tell application "Microsoft Outlook"',
        '    repeat with m in msgs',
        '      if (|to| of m) is not "" then',
        '        set newMsg to make new outgoing message with properties '
        '{subject:(|subj| of m), plain text content:(|body| of m)}',
        '        make new recipient at newMsg with properties '
        '{email address:{address:(|to| of m)}}',
        '        send newMsg',
        '        set sentCount to sentCount + 1',
        '      end if',
        '    end repeat',
        '  end tell',
        'else',
        '  tell application "Mail"',
        '    repeat with m in msgs',
        '      if (|to| of m) is not "" then',
        '        set newMsg to make new outgoing message with properties '
        '{subject:(|subj| of m), content:(|body| of m), visible:false}',
        '        tell newMsg',
        '          make new to recipient at end of to recipients with properties '
        '{address:(|to| of m)}',
        '        end tell',
        '        send newMsg',
        '        set sentCount to sentCount + 1',
        '      end if',
        '    end repeat',
        '  end tell',
        'end if',
        'display dialog "Sent " & sentCount & " message(s)." buttons {"OK"} default button "OK"',
    ]
    return "\n".join(lines) + "\n"


_README = (
    "TeamForge - auto-send pack\n"
    "==========================\n\n"
    "This folder sends every email for you through the mail app already on your\n"
    "computer. UNZIP it first (don't run anything from inside the .zip), then just\n"
    "DOUBLE-CLICK the one file for your computer:\n\n"
    "  WINDOWS (Outlook):            double-click  'Send emails (Windows).cmd'\n"
    "  MAC (Outlook or Apple Mail):  double-click  'send_all_mac.applescript',\n"
    "                                then click Run. Pick your mail app when asked.\n\n"
    "On Windows, if you see 'Windows protected your PC', click 'More info' then\n"
    "'Run anyway'. The first time, approve the prompt letting it control the mail\n"
    "app. Messages send from your own account.\n"
)


def send_all_pack(messages: List[mail.Message], folder_label: str = "Emails") -> bytes:
    parts = parts_from_messages(messages)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Send emails (Windows).cmd", _windows_launcher())
        z.writestr("send_all_windows.ps1", _powershell(parts))
        z.writestr("send_all_mac.applescript", _applescript(parts))
        z.writestr("READ ME FIRST.txt", _README)
    return buf.getvalue()
