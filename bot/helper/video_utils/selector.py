from __future__ import annotations
from aiofiles.os import path as aiopath
from ast import literal_eval
from asyncio import Event, wait_for, gather
from functools import partial
from os import makedirs
from os import path as ospath
from PIL import Image
from pyrogram.filters import regex, user
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.types import Message, CallbackQuery
from re import match as re_match
from time import time

from bot.core.config_manager import Config
from bot.helper.ext_utils.bot_utils import new_task, sync_to_async
from bot.helper.ext_utils.files_utils import clean_target
from bot.helper.ext_utils.status_utils import get_readable_time
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.telegram_helper.filters import CustomFilters
from bot.helper.telegram_helper.message_utils import (
    send_message,
    edit_message,
    delete_message,
)
from bot.helper.video_utils import VID_MODE


class SelectMode:
    def __init__(self, listener, is_link=False):
        self._is_link = is_link
        self._time = time()
        self._reply = None
        self.listener = listener
        self.is_rename = False
        self.mode = ''
        self.extra_data = {}
        self.newname = ''
        self.event = Event()
        self.message_event = Event()
        self.is_cancelled = False

    async def _event_handler(self):
        pfunc = partial(cb_vidtools, obj=self)
        handler = self.listener.client.add_handler(
            CallbackQueryHandler(
                pfunc,
                filters=regex('^vidtool') & user(self.listener.user_id),
            ),
            group=-1,
        )
        try:
            await wait_for(self.event.wait(), timeout=180)
        except Exception:
            self.mode = 'Task has been cancelled, time out!'
            self.is_cancelled = True
            self.event.set()
        finally:
            self.listener.client.remove_handler(*handler)

    async def message_event_handler(self, mode=''):
        is_sub = mode == 'subfile'
        pfunc = partial(message_handler, obj=self, is_sub=is_sub)
        handler = self.listener.client.add_handler(
            MessageHandler(pfunc, user(self.listener.user_id)),
            group=1,
        )
        try:
            await wait_for(self.message_event.wait(), timeout=60)
        except Exception:
            self.message_event.set()
        finally:
            self.listener.client.remove_handler(*handler)
            self.message_event.clear()

    async def _send_message(self, text: str, buttons):
        if not self._reply:
            self._reply = await send_message(self.listener.message, text, buttons)
        else:
            await edit_message(self._reply, text, buttons)

    def _captions(self, mode: str = None):
        mode_icons = {
            'vid_vid': '🎞️', 'vid_aud': '🎵', 'vid_sub': '📝', 'subsync': '🔄',
            'compress': '🗜️', 'convert': '♻️', 'watermark': '💧',
            'extract': '📤', 'trim': '✂️', 'rmstream': '🚫',
        }
        mode_desc = {
            'vid_vid':  'Merge two or more video files into one output.',
            'vid_aud':  'Mux extra audio track(s) into a video.',
            'vid_sub':  'Mux subtitle file(s) into a video (soft / hardsub).',
            'subsync':  'Auto / manually sync subtitle timings to the video.',
            'compress': 'Re-encode the video to a smaller size with chosen quality.',
            'convert':  'Change resolution to a different format.',
            'watermark': 'Burn an image watermark (or text) onto the video.',
            'extract':  'Pull out video / audio / subtitle streams as files.',
            'trim':     'Cut a section from the video using a time range.',
            'rmstream': 'Remove unwanted audio / subtitle streams from the video.',
        }
        header = '┌━━━«★彡 <b>VIDEO TOOLS</b> 彡★»━━━'
        footer = '└━━━«★彡 <b>SS Bots</b> 彡★»━━━'
        lines = [header]
        vidmode = VID_MODE.get(self.mode)
        icon = mode_icons.get(self.mode, '🎬')
        if vidmode:
            lines.append(f'├ {icon} <b>Mode :</b> <i>{vidmode}</i>')
            if desc := mode_desc.get(self.mode):
                lines.append(f'├ 💡 <b>About :</b> <i>{desc}</i>')
        else:
            lines.append('├ 🎬 <b>Mode :</b> <i>Not selected</i>')
            lines.append('├ 💡 <b>Tip :</b> <i>Pick a tool below to get started.</i>')
        lines.append(f'├ 📝 <b>Name :</b> <code>{self.newname or "Default"}</code>')
        if self.mode in ('vid_sub', 'watermark'):
            hardsub = self.extra_data.get('hardsub')
            lines.append(f"├ 🔥 <b>Hardsub :</b> {'✅ Enabled' if hardsub else '❌ Disabled'}")
            if hardsub:
                lines.append(
                    f"├ 🅱️ <b>Bold Style :</b> "
                    f"{'✅ On' if self.extra_data.get('boldstyle') else '❌ Off'}"
                )
                if fontname := (
                    self.extra_data.get('fontname') or
                    getattr(Config, 'VT_HARDSUB_FONT_NAME', '')
                ):
                    lines.append(f"├ 🔤 <b>Font Name :</b> <i>{fontname.replace('_', ' ')}</i>")
                if fontsize := (
                    self.extra_data.get('fontsize') or
                    getattr(Config, 'VT_HARDSUB_FONT_SIZE', '')
                ):
                    lines.append(f'├ 🔡 <b>Font Size :</b> <i>{fontsize}</i>')
                if fontcolour := self.extra_data.get('fontcolour'):
                    lines.append(f'├ 🎨 <b>Font Colour :</b> <code>#{fontcolour}</code>')
        if self.mode == 'watermark':
            wmtype = self.extra_data.get('wmtype')
            if wmtype:
                lines.append(f'├ 🧩 <b>WM Type :</b> <i>{wmtype.title()}</i>')
            if wmtype == 'text' and (wmtext := self.extra_data.get('wmtext')):
                lines.append(f'├ ✍️ <b>WM Text :</b> <code>{wmtext}</code>')
            if wmtype == 'logo':
                lines.append(f'├ 🖼️ <b>WM Logo :</b> <i>{"✅ Received" if self.extra_data.get("wm_logo_ok") else "⏳ Pending"}</i>')
            if fontcolour := self.extra_data.get('fontcolour'):
                lines.append(f'├ 🎨 <b>WM Colour :</b> <code>#{fontcolour}</code>')
            if quality := self.extra_data.get('quality'):
                lines.append(f'├ 📺 <b>Quality :</b> <i>{quality}</i>')
            if wmsize := self.extra_data.get('wmsize'):
                lines.append(f'├ 📐 <b>WM Size :</b> <i>{wmsize}%</i>')
            if wmposition := self.extra_data.get('wmposition'):
                pos_dict = {
                    '5:5': '↖️ Top Left',
                    'main_w-overlay_w-5:5': '↗️ Top Right',
                    '5:main_h-overlay_h': '↙️ Bottom Left',
                    'w-overlay_w-5:main_h-overlay_h-5': '↘️ Bottom Right',
                    '(main_w-overlay_w)/2:(main_h-overlay_h)/2': '⬛ Center',
                }
                lines.append(f'├ 📍 <b>WM Position :</b> <i>{pos_dict.get(wmposition, wmposition)}</i>')
            if popupwm := self.extra_data.get('popupwm'):
                lines.append(f'├ 💫 <b>Display :</b> <i>{popupwm}x / 20s</i>')
        elif self.mode != 'watermark':
            if quality := self.extra_data.get('quality'):
                lines.append(f'├ 📺 <b>Quality :</b> <i>{quality}</i>')
        if self.mode == 'subsync' and (typee := self.extra_data.get('type')):
            lines.append(f'├ 🔄 <b>Sync Mode :</b> <i>{typee.lstrip("sync_").title()}</i>')
        lines.append(footer)
        msg = '\n'.join(lines)

        wmtype = self.extra_data.get('wmtype', '')
        prompts = {
            'rename':    '\n\n📝 <i>Send a valid file name with extension…</i>',
            'watermark': '\n\n💧 <i>Select watermark type below — PNG Logo or Text.</i>',
            'wmtype':    (
                '\n\n🖼️ <i>Send the PNG logo file as a document…</i>'
                if wmtype == 'logo'
                else '\n\n✍️ <i>Send the watermark text message…</i>'
                if wmtype == 'text'
                else '\n\n💧 <i>Select a type above, then send the watermark content.</i>'
            ),
            'subfile':   '\n\n📄 <i>Send a subtitle file (.ass or .srt) for hardsub…</i>',
            'wmsize':    '\n\n📐 <i>Pick the watermark size (% of video width)</i>',
            'wmposition':'\n\n📍 <i>Pick the watermark position on the video</i>',
            'wmcolor':   '\n\n🎨 <i>Pick a text colour for the watermark</i>',
            'popupwm':   '\n\n💫 <i>How many times should watermark appear? (every 20s)</i>',
            'fontsize':  (
                '\n\n🔡 <i>Pick a font size</i>\n'
                '<b>Recommended:</b>\n'
                '• 1080p — <b>21-26</b>\n'
                '• 720p  — <b>16-21</b>\n'
                '• 480p  — <b>11-16</b>'
            ),
        }
        if mode in prompts:
            msg += prompts[mode]
        msg += f'\n\n⏳ <i>Time Out :</i> <b>{get_readable_time(180 - (time() - self._time))}</b>'
        return f'<blockquote>{msg}</blockquote>'

    async def list_buttons(self, mode: str = ''):
        buttons, bnum = ButtonMaker(), 2
        mode_btn_labels = {
            'vid_vid':  '🎞️ Video + Video',
            'vid_aud':  '🎵 Video + Audio',
            'vid_sub':  '📝 Video + Subtitle',
            'subsync':  '🔄 SubSync',
            'compress': '🗜️ Compress',
            'convert':  '♻️ Convert',
            'watermark': '💧 Watermark',
            'extract':  '📤 Extract',
            'trim':     '✂️ Trim',
            'rmstream': '🚫 Remove Stream',
        }
        if not mode:
            # ── Main mode selection ──────────────────────────────────────
            vid_modes = (
                dict(list(VID_MODE.items())[4:]) if self._is_link else VID_MODE
            )
            for key, value in vid_modes.items():
                label = mode_btn_labels.get(key, value)
                buttons.data_button(
                    f"{'✅ ' if self.mode == key else ''}{label}",
                    f'vidtool {key}',
                )
            buttons.data_button(
                f'{"✅ " if self.newname else "✏️ "}Rename',
                'vidtool rename', 'header',
            )
            buttons.data_button('❌ Cancel', 'vidtool cancel', 'footer')
            if self.mode:
                buttons.data_button('✔️ Done', 'vidtool done', 'footer')
            if self.mode in ('vid_sub', 'watermark') and await CustomFilters.sudo(
                '', self.listener.message
            ):
                hardsub = self.extra_data.get('hardsub')
                buttons.data_button(
                    f"{'✅ ' if hardsub else '🔥 '}Hardsub",
                    'vidtool hardsub', 'header',
                )
                if hardsub:
                    if self.mode == 'watermark':
                        has_sub = await aiopath.exists(
                            self.extra_data.get('subfile', '')
                        )
                        buttons.data_button(
                            f"{'✅ ' if has_sub else '📄 '}Sub File",
                            'vidtool subfile', 'header',
                        )
                    buttons.data_button('🅰️ Font Style', 'vidtool fontstyle', 'header')

            # Watermark / Compress quick-access buttons in main menu
            if self.mode == 'watermark':
                buttons.data_button('🖼️ Watermark Options', 'vidtool wm_menu', 'header')
                buttons.data_button('📺 Quality', 'vidtool quality', 'header')
            elif self.mode == 'compress':
                buttons.data_button('📺 Quality', 'vidtool quality', 'header')

        elif self.mode == 'watermark':
            # ── Watermark sub-menus ──────────────────────────────────────
            wmtype = self.extra_data.get('wmtype', '')
            wm_content_ok = (
                (wmtype == 'text' and self.extra_data.get('wmtext')) or
                (wmtype == 'logo' and self.extra_data.get('wm_logo_ok'))
            )

            match mode:
                case 'watermark' | 'wm_menu':
                    # Type selector + settings (after content received)
                    buttons.data_button(
                        f"{'✅ ' if wmtype == 'logo' else '🖼️ '}PNG Logo",
                        'vidtool wmtype logo',
                    )
                    buttons.data_button(
                        f"{'✅ ' if wmtype == 'text' else '✍️ '}Text Watermark",
                        'vidtool wmtype text',
                    )
                    if wm_content_ok:
                        buttons.data_button('📍 Position', 'vidtool wmposition_open', 'header')
                        buttons.data_button('💫 Popup', 'vidtool popupwm', 'header')
                        if wmtype == 'logo':
                            buttons.data_button('📐 Size', 'vidtool wmsize_open', 'header')
                        if wmtype == 'text':
                            buttons.data_button('🎨 Colour', 'vidtool wmcolor', 'header')
                    buttons.data_button('« Back', 'vidtool back', 'footer')
                    buttons.data_button('✔️ Done', 'vidtool done', 'footer')

                case 'wmtype':
                    # Waiting for user to send content
                    buttons.data_button(
                        f"{'✅ ' if wmtype == 'logo' else '🖼️ '}PNG Logo",
                        'vidtool wmtype logo',
                    )
                    buttons.data_button(
                        f"{'✅ ' if wmtype == 'text' else '✍️ '}Text Watermark",
                        'vidtool wmtype text',
                    )
                    buttons.data_button('« Back', 'vidtool wm_menu', 'footer')
                    buttons.data_button('✔️ Done', 'vidtool done', 'footer')

                case 'wmsize':
                    bnum = 3
                    for btn in [5, 10, 15, 20, 25, 30]:
                        buttons.data_button(
                            f"{'✅ ' if str(btn) == str(self.extra_data.get('wmsize')) else ''}{btn}%",
                            f'vidtool wmsize {btn}',
                        )
                    buttons.data_button('« Back', 'vidtool wm_menu', 'footer')
                    buttons.data_button('✔️ Done', 'vidtool done', 'footer')

                case 'wmposition':
                    cur = self.extra_data.get('wmposition')
                    positions = [
                        ('↖️ Top Left',    '5:5'),
                        ('↗️ Top Right',   'main_w-overlay_w-5:5'),
                        ('↙️ Bottom Left', '5:main_h-overlay_h'),
                        ('↘️ Bottom Right','w-overlay_w-5:main_h-overlay_h-5'),
                        ('⬛ Center',      '(main_w-overlay_w)/2:(main_h-overlay_h)/2'),
                    ]
                    for label, val in positions:
                        buttons.data_button(
                            f"{'✅ ' if cur == val else ''}{label}",
                            f'vidtool wmposition {val}',
                        )
                    buttons.data_button('« Back', 'vidtool wm_menu', 'footer')
                    buttons.data_button('✔️ Done', 'vidtool done', 'footer')

                case 'wmcolor':
                    bnum = 3
                    colours = [
                        ('🔴 Red',         '0000ff'),
                        ('🟢 Green',        '00ff00'),
                        ('🔵 Blue',         'ff0000'),
                        ('🟡 Yellow',       '00ffff'),
                        ('🟠 Orange',       '0054ff'),
                        ('🟣 Purple',       '005aff'),
                        ('🌸 Soft Red',     'd470ff'),
                        ('🍃 Soft Green',   '80ff80'),
                        ('💧 Soft Blue',    'ffb84d'),
                        ('🌼 Soft Yellow',  '80ffff'),
                        ('⬜ White',        'ffffff'),
                        ('⬛ Black',        '000000'),
                    ]
                    for btn, hexcolour in colours:
                        buttons.data_button(
                            f"{'✅ ' if hexcolour == self.extra_data.get('fontcolour') else ''}{btn}",
                            f'vidtool wmcolor {hexcolour}',
                        )
                    buttons.data_button('« Back', 'vidtool wm_menu', 'footer')
                    buttons.data_button('✔️ Done', 'vidtool done', 'footer')

                case 'popupwm':
                    bnum = 5
                    popupwm = self.extra_data.get('popupwm', 0)
                    if popupwm:
                        buttons.data_button('🔄 Reset', 'vidtool popupwm 0', 'header')
                    for key in range(2, 21, 2):
                        buttons.data_button(
                            f"{'✅ ' if popupwm == key else ''}{key}",
                            f'vidtool popupwm {key}',
                        )
                    buttons.data_button('« Back', 'vidtool wm_menu', 'footer')
                    buttons.data_button('✔️ Done', 'vidtool done', 'footer')

                case 'quality':
                    bnum = 3
                    for key in ['1080p', '720p', '540p', '480p', '360p']:
                        buttons.data_button(
                            f"{'✅ ' if self.extra_data.get('quality') == key else ''}{key}",
                            f'vidtool quality {key}',
                        )
                    buttons.data_button('« Back', 'vidtool wm_menu', 'footer')
                    buttons.data_button('✔️ Done', 'vidtool done', 'footer')

                case _:
                    buttons.data_button('« Back', 'vidtool wm_menu', 'footer')
                    buttons.data_button('✔️ Done', 'vidtool done', 'footer')

        else:
            # ── Non-watermark sub-menus (compress, hardsub, fontstyle, etc.) ─
            def _buttons_style(name=True, size=True, colour=True, position='header', cb='fontstyle'):
                if name:
                    buttons.data_button('🔤 Font Name', 'vidtool fontstyle fontname', position)
                if size:
                    buttons.data_button('🔡 Font Size', 'vidtool fontstyle fontsize', position)
                if colour:
                    buttons.data_button('🎨 Font Colour', 'vidtool fontstyle fontcolour', position)
                buttons.data_button('« Back', f'vidtool {cb}', 'footer')
                buttons.data_button('✔️ Done', 'vidtool done', 'footer')

            match mode:
                case 'subsync':
                    buttons.data_button('🛠️ Manual', 'vidtool sync_manual')
                    buttons.data_button('⚡ Auto', 'vidtool sync_auto')
                case 'quality':
                    bnum = 3
                    for key in ['1080p', '720p', '540p', '480p', '360p']:
                        buttons.data_button(
                            f"{'✅ ' if self.extra_data.get('quality') == key else ''}{key}",
                            f'vidtool quality {key}',
                        )
                    buttons.data_button('« Back', 'vidtool back', 'footer')
                    buttons.data_button('✔️ Done', 'vidtool done', 'footer')
                case 'popupwm':
                    bnum = 5
                    popupwm = self.extra_data.get('popupwm', 0)
                    if popupwm:
                        buttons.data_button('🔄 Reset', 'vidtool popupwm 0', 'header')
                    for key in range(2, 21, 2):
                        buttons.data_button(
                            f"{'✅ ' if popupwm == key else ''}{key}",
                            f'vidtool popupwm {key}',
                        )
                    buttons.data_button('« Back', 'vidtool back', 'footer')
                    buttons.data_button('✔️ Done', 'vidtool done', 'footer')
                case 'wmsize':
                    bnum = 3
                    for btn in [5, 10, 15, 20, 25, 30]:
                        buttons.data_button(
                            f"{'✅ ' if str(btn) == str(self.extra_data.get('wmsize')) else ''}{btn}",
                            f'vidtool wmsize {btn}',
                        )
                case 'fontstyle':
                    bnum = 3
                    _buttons_style(position=None, cb='back')
                    buttons.data_button(
                        f"{'✅ ' if self.extra_data.get('boldstyle') else '🅱️ '}Bold Style",
                        f"vidtool fontstyle boldstyle {self.extra_data.get('boldstyle', False)}",
                        'header',
                    )
                case 'fontname':
                    _buttons_style(name=False)
                    for btn in [
                        'Arial', 'Impact', 'Verdana', 'Consolas',
                        'DejaVu_Sans', 'Comic_Sans_MS', 'Simple_Day_Mistu',
                    ]:
                        buttons.data_button(
                            f"{'✅ ' if btn == self.extra_data.get('fontname') else ''}"
                            f"{btn.replace('_', ' ')}",
                            f'vidtool fontstyle fontname {btn}',
                        )
                case 'fontsize':
                    bnum = 5
                    _buttons_style(size=False)
                    for btn in range(11, 31):
                        buttons.data_button(
                            f"{'✅ ' if str(btn) == str(self.extra_data.get('fontsize')) else ''}{btn}",
                            f'vidtool fontstyle fontsize {btn}',
                        )
                case 'fontcolour':
                    bnum = 3
                    _buttons_style(colour=False)
                    colours = [
                        ('🔴 Red', '0000ff'), ('🟢 Green', '00ff00'),
                        ('🔵 Blue', 'ff0000'), ('🟡 Yellow', '00ffff'),
                        ('🟠 Orange', '0054ff'), ('🟣 Purple', '005aff'),
                        ('🌸 Soft Red', 'd470ff'), ('🍃 Soft Green', '80ff80'),
                        ('💧 Soft Blue', 'ffb84d'), ('🌼 Soft Yellow', '80ffff'),
                    ]
                    for btn, hexcolour in colours:
                        buttons.data_button(
                            f"{'✅ ' if hexcolour == self.extra_data.get('fontcolour') else ''}{btn}",
                            f'vidtool fontstyle fontcolour {hexcolour}',
                        )
                case 'wmposition':
                    cur = self.extra_data.get('wmposition')
                    positions = [
                        ('↖️ Top Left',    '5:5'),
                        ('↗️ Top Right',   'main_w-overlay_w-5:5'),
                        ('↙️ Bottom Left', '5:main_h-overlay_h'),
                        ('↘️ Bottom Right','w-overlay_w-5:main_h-overlay_h-5'),
                        ('⬛ Center',      '(main_w-overlay_w)/2:(main_h-overlay_h)/2'),
                    ]
                    for label, val in positions:
                        buttons.data_button(
                            f"{'✅ ' if cur == val else ''}{label}",
                            f'vidtool wmposition {val}',
                        )
                    buttons.data_button('« Back', 'vidtool watermark', 'footer')
                    buttons.data_button('✔️ Done', 'vidtool done', 'footer')
                case _:
                    buttons.data_button('« Back', 'vidtool back', 'footer')

        await self._send_message(self._captions(mode), buttons.build_menu(bnum, 3))

    async def get_buttons(self):
        future = self._event_handler()
        await gather(self.list_buttons(), future)
        if self.is_cancelled:
            await edit_message(self._reply, self.mode)
            return
        await delete_message(self._reply)
        return [self.mode, self.newname, self.extra_data]


async def message_handler(_, message: Message, obj: SelectMode, is_sub=False):
    data = None
    if obj.is_rename and message.text:
        obj.newname = message.text.strip().replace('/', '')
        obj.is_rename = False
    elif obj.mode == 'watermark':
        wmtype = obj.extra_data.get('wmtype')
        media = message.photo or message.document or message.sticker
        if wmtype == 'text':
            if not message.text:
                await send_message(message, '❌ Send watermark text only (no files).')
                return
            obj.extra_data['wmtext'] = message.text.strip()
            obj.extra_data['wm_logo_ok'] = False
            data = 'watermark'
        elif wmtype == 'logo':
            if not media:
                await send_message(message, '❌ Send a PNG logo file as document.')
                return
            fname = getattr(media, 'file_name', '') or ''
            mime = getattr(media, 'mime_type', '') or ''
            if not fname.lower().endswith('.png'):
                await send_message(message, '❌ Only PNG logo is allowed! Send a .png file.')
                return
            if message.document and 'image' not in mime and mime != 'application/octet-stream':
                await send_message(message, '❌ Only PNG image document allowed!')
                return
            await sync_to_async(makedirs, 'watermark', exist_ok=True)
            fpath = await message.download(
                ospath.join('watermark', getattr(media, 'file_id', 'wm'))
            )
            await sync_to_async(
                lambda: Image.open(fpath).convert('RGBA').save(
                    ospath.join('watermark', f'{obj.listener.mid}.png'), 'PNG'
                )
            )
            await clean_target(fpath)
            obj.extra_data['wm_logo_ok'] = True
            data = 'watermark'
        else:
            await send_message(
                message,
                '❌ Choose PNG Logo or Text Watermark type first using the buttons above.',
            )
            return
    obj.message_event.set()
    await gather(obj.list_buttons(data), delete_message(message))


@new_task
async def cb_vidtools(_, query: CallbackQuery, obj: SelectMode):
    data = query.data.split()
    disable_modes = getattr(Config, 'VT_DISABLE_MODES', [])
    if data[1] in disable_modes:
        await query.answer(f'{VID_MODE.get(data[1], data[1])} has been disabled!', True)
        return
    await query.answer()

    # Allow re-clicking watermark and its navigation callbacks without early-return
    _nav_cmds = {
        'watermark', 'wm_menu', 'wmtype', 'wmsize', 'wmposition',
        'wmsize_open', 'wmposition_open', 'wmcolor',
        'quality', 'popupwm', 'back', 'done', 'cancel',
        'hardsub', 'subfile', 'fontstyle', 'sync_manual', 'sync_auto',
    }
    if data[1] == obj.mode and data[1] not in _nav_cmds:
        return

    match data[1]:
        case 'done':
            obj.event.set()

        case 'back':
            if obj.message_event.is_set() is False:
                obj.message_event.set()
            await obj.list_buttons()

        case 'cancel':
            obj.mode = 'Task has been cancelled!'
            obj.is_cancelled = True
            obj.event.set()

        case 'quality':
            if len(data) == 3:
                obj.extra_data['quality'] = data[2]
                await obj.list_buttons()
            else:
                await obj.list_buttons('quality')

        case 'popupwm':
            if len(data) == 3:
                obj.extra_data['popupwm'] = int(data[2])
                if obj.mode == 'watermark':
                    await obj.list_buttons('watermark')
                    return
            await obj.list_buttons('popupwm')

        case 'wm_menu':
            # Open the watermark options submenu
            await obj.list_buttons('watermark')

        case 'wmtype':
            # User picked logo or text — set type and start waiting for content
            if len(data) == 3:
                new_type = data[2]
                if obj.extra_data.get('wmtype') != new_type:
                    obj.extra_data['wmtype'] = new_type
                    obj.extra_data.pop('wmtext', None)
                    obj.extra_data.pop('wm_logo_ok', None)
                # Trigger any pending message event so we start fresh
                obj.message_event.set()
                obj.message_event.clear()
                # Start message listener and show prompt
                future = obj.message_event_handler('wmtype')
                await gather(obj.list_buttons('wmtype'), future)

        case 'wmcolor':
            # Store colour under 'fontcolour' so executor.py picks it up correctly
            if len(data) == 3:
                obj.extra_data['fontcolour'] = data[2]
            await obj.list_buttons('watermark')

        case 'wmsize_open':
            # Open the size picker submenu
            await obj.list_buttons('wmsize')

        case 'wmposition_open':
            # Open the position picker submenu
            await obj.list_buttons('wmposition')

        case 'wmsize' | 'wmposition' as value:
            # data[2] is the chosen value; go back to watermark submenu after
            if len(data) == 3:
                obj.extra_data[value] = data[2]
            await obj.list_buttons('watermark')

        case 'hardsub':
            hmode = not bool(obj.extra_data.get('hardsub'))
            if not hmode and obj.mode == 'vid_sub':
                obj.extra_data.clear()
            obj.extra_data['hardsub'] = hmode
            await obj.list_buttons()

        case 'subfile':
            future = obj.message_event_handler('subfile')
            await gather(obj.list_buttons('subfile'), future)

        case 'fontstyle':
            mode = 'fontstyle'
            if len(data) > 2:
                mode = data[2]
                is_bold = mode == 'boldstyle'
                if len(data) == 4:
                    if not is_bold and obj.extra_data.get(mode) == data[3]:
                        return
                    obj.extra_data[mode] = (
                        not literal_eval(data[3]) if is_bold else data[3]
                    )
                if is_bold:
                    mode = 'fontstyle'
            await obj.list_buttons(mode)

        case 'sync_manual' | 'sync_auto' as value:
            obj.extra_data['type'] = value
            await obj.list_buttons()

        case value:
            if value == 'rename':
                obj.is_rename = True
                future = obj.message_event_handler(value)
                await gather(obj.list_buttons(value), future)
                return
            elif value == 'compress':
                # Compress tool is restricted to sudo/admin users only
                if not await CustomFilters.sudo('', query):
                    await query.answer(
                        '🚫 Compress tool is Avilable to Admins/Sudo users only!',
                        show_alert=True,
                    )
                    return
                obj.mode = value
                obj.extra_data.clear()
            else:
                obj.mode = value
                obj.extra_data.clear()

            if value == 'watermark':
                # Show watermark type-selection submenu directly
                await obj.list_buttons('watermark')
                return

            await obj.list_buttons('subsync' if value == 'subsync' else '')

