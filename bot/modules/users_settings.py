from asyncio import sleep
from functools import partial
from html import escape
from io import BytesIO
from os import getcwd
from re import sub
from time import time

from aiofiles.os import makedirs, remove
from aiofiles.os import path as aiopath
from langcodes import Language
from pyrogram.filters import create
from pyrogram.handlers import MessageHandler

from bot.helper.ext_utils.status_utils import get_readable_file_size

from .. import auth_chats, excluded_extensions, sudo_users, user_data
from ..core.config_manager import Config
from ..core.tg_client import TgClient
from ..helper.ext_utils.bot_utils import (
    get_size_bytes,
    new_task,
    update_user_ldata,
)
from ..helper.video_utils import VID_MODE
from ..helper.ext_utils.db_handler import database
from ..helper.ext_utils.media_utils import create_thumb
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    send_file,
    send_message,
)

handler_dict = {}

leech_options = [
    "THUMBNAIL",
    "LEECH_SPLIT_SIZE",
    "LEECH_DUMP_CHAT",
    "LEECH_PREFIX",
    "LEECH_SUFFIX",
    "LEECH_CAPTION",
    "THUMBNAIL_LAYOUT",
]
uphoster_options = [
    "GOFILE_TOKEN",
    "GOFILE_FOLDER_ID",
    "BUZZHEAVIER_TOKEN",
    "BUZZHEAVIER_FOLDER_ID",
    "PIXELDRAIN_KEY",
]
rclone_options = ["RCLONE_CONFIG", "RCLONE_PATH", "RCLONE_FLAGS"]
gdrive_options = ["TOKEN_PICKLE", "GDRIVE_ID", "INDEX_URL"]
ffset_options = [
    "FFMPEG_CMDS",
    "METADATA",
    "AUDIO_METADATA",
    "VIDEO_METADATA",
    "SUBTITLE_METADATA",
]
advanced_options = [
    "EXCLUDED_EXTENSIONS",
    "NAME_SWAP",
    "YT_DLP_OPTIONS",
    "UPLOAD_PATHS",
    "USER_COOKIE_FILE",
]
yt_options = ["YT_DESP", "YT_TAGS", "YT_CATEGORY_ID", "YT_PRIVACY_STATUS"]

_COMPRESS_PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium"]

_VID_ICONS = {
    "vid_vid":   "🎞️",
    "vid_aud":   "🎵",
    "vid_sub":   "📝",
    "subsync":   "🔄",
    "compress":  "🗜️",
    "convert":   "🔁",
    "watermark": "💧",
    "extract":   "📤",
    "trim":      "✂️",
    "rmstream":  "🗑️",
}

_VID_FIELD_OPTIONS = {
    "vid_merge_mode":     ["sequential", "concat"],
    "vid_audio_codec":    ["aac", "mp3", "ac3", "opus"],
    "vid_convert_format": ["mp4", "mkv", "webm", "mov"],
    "vid_watermark_pos":  ["top-left", "top-right", "bottom-left", "bottom-right", "center"],
}

_VID_MULTI_OPTIONS = {
    "vid_extract_streams": ["video", "audio", "subtitle"],
    "vid_rmstream_kind":   ["audio", "subtitle"],
}

_VID_DEFAULTS = {
    "vid_merge_mode":        "sequential",
    "vid_audio_lang":        "",
    "vid_audio_codec":       "aac",
    "vid_subsync_delay":     "0",
    "vid_convert_format":    "mp4",
    "vid_watermark_text":    "",
    "vid_watermark_pos":     "bottom-right",
    "vid_watermark_opacity": "50",
    "vid_extract_streams":   ["audio", "subtitle"],
    "vid_trim_start":        "00:00:00",
    "vid_trim_end":          "00:00:00",
    "vid_rmstream_kind":     [],
}

_VID_SETTING_MAP = {
    "vid_vid":   "vid_merge",
    "vid_aud":   "vid_audmux",
    "vid_sub":   "vid_hardsub",
    "subsync":   "vid_subsync",
    "compress":  "vid_compress",
    "convert":   "vid_convert",
    "watermark": "vid_watermark",
    "extract":   "vid_extract",
    "trim":      "vid_trim",
    "rmstream":  "vid_rmstream",
}

_TOGGLE_BACK_MAP = {
    "vid_vid":   "vid_merge",
    "vid_aud":   "vid_audmux",
    "vid_sub":   "vid_hardsub",
    "subsync":   "vid_subsync",
    "compress":  "vid_compress",
    "convert":   "vid_convert",
    "watermark": "vid_watermark",
    "extract":   "vid_extract",
    "trim":      "vid_trim",
    "rmstream":  "vid_rmstream",
}

_VID_INPUT_MAP = {
    "vid_audio_lang":        ("Audio Language",    "Send ISO 639 language code (e.g. <code>eng</code>, <code>hin</code>, <code>jpn</code>).", "vid_audmux"),
    "vid_subsync_delay":     ("Sync Delay (ms)",   "Send delay in ms. Positive delays subs, negative advances (e.g. <code>-500</code>).",    "vid_subsync"),
    "vid_watermark_text":    ("Watermark Text",    "Send text to use as watermark (e.g. <code>@MyChannel</code>).",                          "vid_watermark"),
    "vid_watermark_opacity": ("Opacity (%)",       "Send opacity as number 0–100 (e.g. <code>50</code>).",                                   "vid_watermark"),
    "vid_trim_start":        ("Start Time",        "Send start time in HH:MM:SS (e.g. <code>00:01:30</code>).",                              "vid_trim"),
    "vid_trim_end":          ("End Time",          "Send end time in HH:MM:SS (e.g. <code>00:05:00</code>).",                                "vid_trim"),
    "vid_banner":            ("Compress Banner",   "Send banner text (e.g. <code>Re-Encoded by @MyChannel</code>).",                         "vid_compress"),
    "vid_hardsub_font":      ("HardSub Font",      "Send font name (e.g. <code>Arial</code>).",                                              "vid_hardsub"),
    "vid_hardsub_size":      ("HardSub Font Size", "Send font size as a number (e.g. <code>24</code>).",                                     "vid_hardsub"),
}

user_settings_text = {
    "THUMBNAIL": (
        "Photo or Doc",
        "Custom Thumbnail is used as the thumbnail for the files you upload to telegram in media or document mode.",
        "<i>Send a photo to save it as custom thumbnail.</i> \n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "RCLONE_CONFIG": (
        "",
        "",
        "<i>Send your <code>rclone.conf</code> file to use as your Upload Dest to RClone.</i> \n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "TOKEN_PICKLE": (
        "",
        "",
        "<i>Send your <code>token.pickle</code> to use as your Upload Dest to GDrive</i> \n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "LEECH_SPLIT_SIZE": (
        "",
        "",
        f"Send Leech split size in bytes or use gb or mb. Example: 40000000 or 2.5gb or 1000mb. PREMIUM_USER: {TgClient.IS_PREMIUM_USER}.</i> \n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "LEECH_DUMP_CHAT": (
        "Chat ID / @username / pm",
        "Personal Leech Dump Channel — leech files are also forwarded here after upload.",
        """<i>📤 Send your personal Leech Dump Channel ID or username.</i>

<b>Formats supported:</b>
• Plain chat ID → <code>-1001234567890</code>
• @username → <code>@mychannel</code>
• <code>pm</code> → bot will send files to your private PM
• <code>b:id/@username</code> — force bot session
• <code>u:id/@username</code> — force user session
• <code>h:id/@username</code> — hybrid (bot + user)
• <code>id|topic_id</code> — send to specific forum topic

⏱ <b>Time Left :</b> <code>60 sec</code>""",
    ),
    "LEECH_PREFIX": (
        "",
        "",
        "Send Leech Filename Prefix. You can add HTML tags. Example: <code>@mychannel</code>.</i> \n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "LEECH_SUFFIX": (
        "",
        "",
        "Send Leech Filename Suffix. You can add HTML tags. Example: <code>@mychannel</code>.</i> \n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "LEECH_CAPTION": (
        "",
        "",
        "Send Leech Caption. You can add HTML tags. Example: <code>@mychannel</code>.</i> \n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "THUMBNAIL_LAYOUT": (
        "",
        "",
        "Send thumbnail layout (widthxheight, 2x2, 3x3, 2x4, 4x4, ...). Example: 3x3.</i> \n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "RCLONE_PATH": (
        "",
        "",
        "Send Rclone Path. If you want to use your rclone config edit using owner/user config from usetting or add mrcc: before rclone path. Example mrcc:remote:folder. </i> \n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "RCLONE_FLAGS": (
        "",
        "",
        "key:value|key|key|key:value . Check here all <a href='https://rclone.org/flags/'>RcloneFlags</a>\nEx: --buffer-size:8M|--drive-starred-only",
    ),
    "GDRIVE_ID": (
        "",
        "",
        "Send Gdrive ID. If you want to use your token.pickle edit using owner/user token from usetting or add mtp: before the id. Example: mtp:F435RGGRDXXXXXX . </i> \n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "INDEX_URL": (
        "",
        "",
        "Send Index URL for your gdrive option. </i> \n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "UPLOAD_PATHS": (
        "",
        "",
        "Send Dict of keys that have path values. Example: {'path 1': 'remote:rclonefolder', 'path 2': 'gdrive1 id', 'path 3': 'tg chat id', 'path 4': 'mrcc:remote:', 'path 5': b:@username} . </i> \n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "EXCLUDED_EXTENSIONS": (
        "",
        "",
        "Send exluded extenions seperated by space without dot at beginning. </i> \n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "NAME_SWAP": (
        "",
        "",
        """<i>Send your Name Swap. You can add pattern instead of normal text according to the format.</i>
<b>Full Documentation Guide</b> <a href="https://t.me/WZML_X/77">Click Here</a>
┖ <b>Time Left :</b> <code>60 sec</code>
""",
    ),
    "YT_DLP_OPTIONS": (
        "",
        "",
        """Format: {key: value, key: value, key: value}.
Example: {"format": "bv*+mergeall[vcodec=none]", "nocheckcertificate": True, "playliststart": 10, "fragment_retries": float("inf"), "matchtitle": "S13", "writesubtitles": True, "live_from_start": True, "postprocessor_args": {"ffmpeg": ["-threads", "4"]}, "wait_for_video": (5, 100), "download_ranges": [{"start_time": 0, "end_time": 10}]}
Check all yt-dlp api options from this <a href='https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/YoutubeDL.py#L184'>FILE</a> or use this <a href='https://t.me/mltb_official_channel/177'>script</a> to convert cli arguments to api options.

<i>Send dict of YT-DLP Options according to format.</i> \n┖ <b>Time Left :</b> <code>60 sec</code>""",
    ),
    "FFMPEG_CMDS": (
        "",
        "",
        """Dict of list values of ffmpeg commands. You can set multiple ffmpeg commands for all files before upload. Don't write ffmpeg at beginning, start directly with the arguments.
Examples: {"subtitle": ["-i mltb.mkv -c copy -c:s srt mltb.mkv", "-i mltb.video -c copy -c:s srt mltb"], "convert": ["-i mltb.m4a -c:a libmp3lame -q:a 2 mltb.mp3", "-i mltb.audio -c:a libmp3lame -q:a 2 mltb.mp3"], extract: ["-i mltb -map 0:a -c copy mltb.mka -map 0:s -c copy mltb.srt"]}
Notes:
- Add `-del` to the list which you want from the bot to delete the original files after command run complete!
- To execute one of those lists in bot for example, you must use -ff subtitle (list key) or -ff convert (list key)
Here I will explain how to use mltb.* which is reference to files you want to work on.
1. First cmd: the input is mltb.mkv so this cmd will work only on mkv videos and the output is mltb.mkv also so all outputs is mkv. -del will delete the original media after complete run of the cmd.
2. Second cmd: the input is mltb.video so this cmd will work on all videos and the output is only mltb so the extenstion is same as input files.
3. Third cmd: the input in mltb.m4a so this cmd will work only on m4a audios and the output is mltb.mp3 so the output extension is mp3.
4. Fourth cmd: the input is mltb.audio so this cmd will work on all audios and the output is mltb.mp3 so the output extension is mp3.

<i>Send dict of FFMPEG_CMDS Options according to format.</i> \n┖ <b>Time Left :</b> <code>60 sec</code>
""",
    ),
    "METADATA_CMDS": (
        "",
        "",
        """<i>Send your Meta data. You can according to the format title="Join @WZML_X".</i>
<b>Full Documentation Guide</b> <a href="https://t.me/WZML_X/">Click Here</a>
┖ <b>Time Left :</b> <code>60 sec</code>
""",
    ),
    "METADATA": (
        "🏷 Global Metadata — plain text title OR key=value",
        "Apply metadata to all media files. Plain text sets title on ALL streams automatically.",
        """<i>📝 Two ways to set metadata:</i>

<b>1️⃣ Plain Text (applies title to ALL streams):</b>
Just send your title text → <code>My Movie Title</code>
Bot automatically sets <code>title=My Movie Title</code> on video, audio and subtitle tracks.

<b>2️⃣ Advanced key=value format:</b>
<code>title={basename}|artist={audiolang} Version|year={year}</code>

<b>🔧 Dynamic Variables:</b>
• <code>{filename}</code> - Original filename
• <code>{basename}</code> - Name without extension
• <code>{audiolang}</code> - Audio language (English/Hindi etc.)
• <code>{year}</code> - Year from filename

⏱ <b>Time Left:</b> <code>60 sec</code>""",
    ),
    "AUDIO_METADATA": (
        "🎵 Audio Stream Metadata",
        "Metadata applied to each audio track separately.",
        """<i>🎧 Audio stream metadata with per-track language support</i>

<b>📋 Example:</b>
<code>language={audiolang}|title=Audio - {audiolang}</code>

⏱ <b>Time Left:</b> <code>60 sec</code>""",
    ),
    "VIDEO_METADATA": (
        "🎥 Video Stream Metadata",
        "Metadata applied to video streams.",
        """<i>📹 Video stream metadata for visual tracks</i>

<b>📋 Example:</b>
<code>title={basename}|comment=HD Video</code>

⏱ <b>Time Left:</b> <code>60 sec</code>""",
    ),
    "SUBTITLE_METADATA": (
        "💬 Subtitle Stream Metadata",
        "Metadata applied to each subtitle track separately.",
        """<i>📄 Subtitle stream metadata with per-track language support</i>

<b>📋 Example:</b>
<code>language={sublang}|title=Subtitles - {sublang}</code>

⏱ <b>Time Left:</b> <code>60 sec</code>""",
    ),
    "YT_DESP": (
        "String",
        "Custom description for YouTube uploads. Default is used if not set.",
        "<i>Send your custom YouTube description.</i> \nTime Left : <code>60 sec</code>",
    ),
    "YT_TAGS": (
        "Comma-separated strings",
        "Custom tags for YouTube uploads (e.g., tag1,tag2,tag3). Default is used if not set.",
        "<i>Send your custom YouTube tags as a comma-separated list.</i> \nTime Left : <code>60 sec</code>",
    ),
    "YT_CATEGORY_ID": (
        "Number",
        "Custom category ID for YouTube uploads. Default is used if not set.",
        "<i>Send your custom YouTube category ID (e.g., 22).</i> \nTime Left : <code>60 sec</code>",
    ),
    "YT_PRIVACY_STATUS": (
        "public, private, or unlisted",
        "Custom privacy status for YouTube uploads. Default is used if not set.",
        "<i>Send your custom YouTube privacy status (public, private, or unlisted).</i> \nTime Left : <code>60 sec</code>",
    ),
    "USER_COOKIE_FILE": (
        "File",
        "User's YT-DLP Cookie File to authenticate access to websites and youtube.",
        "<i>Send your cookie file (e.g., cookies.txt or abc.txt).</i> \n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "GOFILE_TOKEN": (
        "String",
        "Gofile API Token",
        "<i>Send your Gofile API Token.</i> \n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "GOFILE_FOLDER_ID": (
        "String",
        "Gofile Folder ID",
        "<i>Send your Gofile Folder ID. If empty, uploads to Root.</i> \n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "BUZZHEAVIER_TOKEN": (
        "String",
        "BuzzHeavier API Token",
        "<i>Send your BuzzHeavier API Token (Account ID).</i> \n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "BUZZHEAVIER_FOLDER_ID": (
        "String",
        "BuzzHeavier Folder ID",
        "<i>Send your BuzzHeavier Folder ID.</i> \n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "PIXELDRAIN_KEY": (
        "String",
        "PixelDrain API Key",
        "<i>Send your PixelDrain API Key.</i> \n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
}


async def get_user_settings(from_user, stype="main"):
    user_id = from_user.id
    user_name = from_user.mention(style="html")
    buttons = ButtonMaker()
    rclone_conf = f"rclone/{user_id}.conf"
    token_pickle = f"tokens/{user_id}.pickle"
    user_dict = user_data.get(user_id, {})

    if stype == "main":
        buttons.data_button(
            "General Settings", f"userset {user_id} general", position="header"
        )
        buttons.data_button("Mirror Settings", f"userset {user_id} mirror")
        buttons.data_button("Leech Settings", f"userset {user_id} leech")
        buttons.data_button("Uphoster Settings", f"userset {user_id} uphoster")
        buttons.data_button("FF Media Settings", f"userset {user_id} ffset")
        buttons.data_button("Video Tools", f"userset {user_id} vidtools")
        buttons.data_button(
            "Mics Settings", f"userset {user_id} advanced", position="l_body"
        )

        if user_dict and any(
            key in user_dict
            for key in list(user_settings_text.keys())
            + [
                "USER_TOKENS",
                "AS_DOCUMENT",
                "EQUAL_SPLITS",
                "MEDIA_GROUP",
                "USER_TRANSMISSION",
                "HYBRID_LEECH",
                "STOP_DUPLICATE",
                "DEFAULT_UPLOAD",
            ]
        ):
            buttons.data_button(
                "Reset All", f"userset {user_id} confirm_reset_all", position="footer"
            )
        buttons.data_button("Close", f"userset {user_id} close", position="footer")

        text = f"""⌬ <b>User Settings :</b>
│
┟ <b>Name</b> → {user_name}
┠ <b>UserID</b> → #ID{user_id}
┠ <b>Username</b> → @{from_user.username}
┠ <b>Telegram DC</b> → {from_user.dc_id}
┖ <b>Telegram Lang</b> → {Language.get(lc).display_name() if (lc := from_user.language_code) else "N/A"}"""

        btns = buttons.build_menu(2)

    elif stype == "general":
        if user_dict.get("DEFAULT_UPLOAD", ""):
            default_upload = user_dict["DEFAULT_UPLOAD"]
        elif "DEFAULT_UPLOAD" not in user_dict:
            default_upload = Config.DEFAULT_UPLOAD
        du = "GDRIVE API" if default_upload == "gd" else "RCLONE"
        dur = "GDRIVE API" if default_upload != "gd" else "RCLONE"
        buttons.data_button(
            f"Swap to {dur} Mode", f"userset {user_id} {default_upload}"
        )

        user_tokens = user_dict.get("USER_TOKENS", False)
        tr = "USER" if user_tokens else "OWNER"
        trr = "OWNER" if user_tokens else "USER"
        buttons.data_button(
            f"Swap to {trr} token/config",
            f"userset {user_id} tog USER_TOKENS {'f' if user_tokens else 't'}",
        )

        buttons.data_button("Back", f"userset {user_id} back", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")

        def_cookies = user_dict.get("USE_DEFAULT_COOKIE", False)
        cookie_mode = "Owner's Cookie" if def_cookies else "User's Cookie"
        buttons.data_button(
            f"Swap to {'OWNER' if not def_cookies else 'USER'}'s Cookie File",
            f"userset {user_id} tog USE_DEFAULT_COOKIE {'f' if def_cookies else 't'}",
        )
        btns = buttons.build_menu(1)

        text = f"""⌬ <b>General Settings :</b>
┟ <b>Name</b> → {user_name}
┃
┠ <b>Default Upload Package</b> → <b>{du}</b>
┠ <b>Default Usage Mode</b> → <b>{tr}'s</b> token/config
┖ <b>yt Cookies Mode</b> → <b>{cookie_mode}</b>
"""

    elif stype == "leech":
        thumbpath = f"thumbnails/{user_id}.jpg"
        buttons.data_button("Thumbnail", f"userset {user_id} menu THUMBNAIL")
        thumbmsg = "Exists" if await aiopath.exists(thumbpath) else "Not Exists"
        buttons.data_button(
            "Leech Split Size", f"userset {user_id} menu LEECH_SPLIT_SIZE"
        )
        if user_dict.get("LEECH_SPLIT_SIZE", False):
            split_size = user_dict["LEECH_SPLIT_SIZE"]
        else:
            split_size = Config.LEECH_SPLIT_SIZE
        buttons.data_button(
            "Leech Destination", f"userset {user_id} menu LEECH_DUMP_CHAT"
        )
        if user_dict.get("LEECH_DUMP_CHAT", False):
            leech_dest = user_dict["LEECH_DUMP_CHAT"]
        elif "LEECH_DUMP_CHAT" not in user_dict and Config.LEECH_DUMP_CHAT:
            leech_dest = Config.LEECH_DUMP_CHAT
        else:
            leech_dest = "None"
        buttons.data_button("Leech Prefix", f"userset {user_id} menu LEECH_PREFIX")
        if user_dict.get("LEECH_PREFIX", False):
            lprefix = user_dict["LEECH_PREFIX"]
        elif "LEECH_PREFIX" not in user_dict and Config.LEECH_PREFIX:
            lprefix = Config.LEECH_PREFIX
        else:
            lprefix = "Not Exists"
        buttons.data_button("Leech Suffix", f"userset {user_id} menu LEECH_SUFFIX")
        if user_dict.get("LEECH_SUFFIX", False):
            lsuffix = user_dict["LEECH_SUFFIX"]
        elif "LEECH_SUFFIX" not in user_dict and Config.LEECH_SUFFIX:
            lsuffix = Config.LEECH_SUFFIX
        else:
            lsuffix = "Not Exists"

        buttons.data_button("Leech Caption", f"userset {user_id} menu LEECH_CAPTION")
        if user_dict.get("LEECH_CAPTION", False):
            lcap = user_dict["LEECH_CAPTION"]
        elif "LEECH_CAPTION" not in user_dict and Config.LEECH_CAPTION:
            lcap = Config.LEECH_CAPTION
        else:
            lcap = "Not Exists"

        if (
            user_dict.get("AS_DOCUMENT", False)
            or "AS_DOCUMENT" not in user_dict
            and Config.AS_DOCUMENT
        ):
            ltype = "DOCUMENT"
            buttons.data_button("Send As Media", f"userset {user_id} tog AS_DOCUMENT f")
        else:
            ltype = "MEDIA"
            buttons.data_button(
                "Send As Document", f"userset {user_id} tog AS_DOCUMENT t"
            )
        if (
            user_dict.get("EQUAL_SPLITS", False)
            or "EQUAL_SPLITS" not in user_dict
            and Config.EQUAL_SPLITS
        ):
            buttons.data_button(
                "Disable Equal Splits", f"userset {user_id} tog EQUAL_SPLITS f"
            )
            equal_splits = "Enabled"
        else:
            buttons.data_button(
                "Enable Equal Splits", f"userset {user_id} tog EQUAL_SPLITS t"
            )
            equal_splits = "Disabled"
        if (
            user_dict.get("MEDIA_GROUP", False)
            or "MEDIA_GROUP" not in user_dict
            and Config.MEDIA_GROUP
        ):
            buttons.data_button(
                "Disable Media Group", f"userset {user_id} tog MEDIA_GROUP f"
            )
            media_group = "Enabled"
        else:
            buttons.data_button(
                "Enable Media Group", f"userset {user_id} tog MEDIA_GROUP t"
            )
            media_group = "Disabled"
        if (
            TgClient.IS_PREMIUM_USER
            and user_dict.get("USER_TRANSMISSION", False)
            or "USER_TRANSMISSION" not in user_dict
            and Config.USER_TRANSMISSION
        ):
            buttons.data_button(
                "Leech by Bot", f"userset {user_id} tog USER_TRANSMISSION f"
            )
            leech_method = "user"
        elif TgClient.IS_PREMIUM_USER:
            leech_method = "bot"
            buttons.data_button(
                "Leech by User", f"userset {user_id} tog USER_TRANSMISSION t"
            )
        else:
            leech_method = "bot"

        if (
            TgClient.IS_PREMIUM_USER
            and user_dict.get("HYBRID_LEECH", False)
            or "HYBRID_LEECH" not in user_dict
            and Config.HYBRID_LEECH
        ):
            hybrid_leech = "Enabled"
            buttons.data_button(
                "Disable Hybride Leech", f"userset {user_id} tog HYBRID_LEECH f"
            )
        elif TgClient.IS_PREMIUM_USER:
            hybrid_leech = "Disabled"
            buttons.data_button(
                "Enable HYBRID Leech", f"userset {user_id} tog HYBRID_LEECH t"
            )
        else:
            hybrid_leech = "Disabled"

        buttons.data_button(
            "Thumbnail Layout", f"userset {user_id} menu THUMBNAIL_LAYOUT"
        )
        if user_dict.get("THUMBNAIL_LAYOUT", False):
            thumb_layout = user_dict["THUMBNAIL_LAYOUT"]
        elif "THUMBNAIL_LAYOUT" not in user_dict and Config.THUMBNAIL_LAYOUT:
            thumb_layout = Config.THUMBNAIL_LAYOUT
        else:
            thumb_layout = "None"

        buttons.data_button("Back", f"userset {user_id} back", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)

        text = f"""⌬ <b>Leech Settings :</b>
┟ <b>Name</b> → {user_name}
┃
┠ Leech Type → <b>{ltype}</b>
┠ Custom Thumbnail → <b>{thumbmsg}</b>
┠ Leech Split Size → <b>{get_readable_file_size(split_size)}</b>
┠ Equal Splits → <b>{equal_splits}</b>
┠ Media Group → <b>{media_group}</b>
┠ Leech Prefix → <code>{escape(lprefix)}</code>
┠ Leech Suffix → <code>{escape(lsuffix)}</code>
┠ Leech Caption → <code>{escape(lcap)}</code>
┠ Leech Destination → <code>{leech_dest}</code>
┠ Leech by <b>{leech_method}</b> session
┠ Mixed Leech → <b>{hybrid_leech}</b>
┖ Thumbnail Layout → <b>{thumb_layout}</b>
"""

    elif stype == "uphoster":
        uphoster_service = user_dict.get("UPHOSTER_SERVICE", "gofile")
        buttons.data_button(
            "Change Destination ⇋",
            f"userset {user_id} uphoster_destinations",
        )
        buttons.data_button("Gofile Tools", f"userset {user_id} gofile")
        buttons.data_button("BuzzHeavier Tools", f"userset {user_id} buzzheavier")
        buttons.data_button("PixelDrain Tools", f"userset {user_id} pixeldrain")
        buttons.data_button("Back", f"userset {user_id} back", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(1)

        destinations = [s.capitalize() for s in uphoster_service.split(",")]
        text = f"""⌬ <b>Uphoster Settings :</b>
┟ <b>Name</b> → {user_name}
┃
┖ <b>Current Destination</b> → {', '.join(destinations)}"""

    elif stype == "pixeldrain":
        buttons.data_button("PixelDrain Key", f"userset {user_id} menu PIXELDRAIN_KEY")
        buttons.data_button("Back", f"userset {user_id} back uphoster", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(1)

        if user_dict.get("PIXELDRAIN_KEY", False):
            pdtoken = user_dict["PIXELDRAIN_KEY"]
        elif Config.PIXELDRAIN_KEY:
            pdtoken = Config.PIXELDRAIN_KEY
        else:
            pdtoken = "None"

        text = f"""⌬ <b>PixelDrain Settings :</b>
┟ <b>Name</b> → {user_name}
┃
┖ <b>PixelDrain Key</b> → <code>{pdtoken}</code>"""

    elif stype == "buzzheavier":
        buttons.data_button(
            "BuzzHeavier Token", f"userset {user_id} menu BUZZHEAVIER_TOKEN"
        )
        buttons.data_button(
            "BuzzHeavier Folder ID", f"userset {user_id} menu BUZZHEAVIER_FOLDER_ID"
        )
        buttons.data_button("Back", f"userset {user_id} back uphoster", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(1)

        if user_dict.get("BUZZHEAVIER_TOKEN", False):
            bztoken = user_dict["BUZZHEAVIER_TOKEN"]
        elif Config.BUZZHEAVIER_API:
            bztoken = Config.BUZZHEAVIER_API
        else:
            bztoken = "None"

        if user_dict.get("BUZZHEAVIER_FOLDER_ID", False):
            bzfolder = user_dict["BUZZHEAVIER_FOLDER_ID"]
        else:
            bzfolder = "None"

        text = f"""⌬ <b>BuzzHeavier Settings :</b>
┟ <b>Name</b> → {user_name}
┃
┠ <b>BuzzHeavier Token</b> → <code>{bztoken}</code>
┖ <b>BuzzHeavier Folder ID</b> → <code>{bzfolder}</code>"""

    elif stype == "gofile":
        buttons.data_button("Gofile Token", f"userset {user_id} menu GOFILE_TOKEN")
        buttons.data_button(
            "Gofile Folder ID", f"userset {user_id} menu GOFILE_FOLDER_ID"
        )
        buttons.data_button("Back", f"userset {user_id} back uphoster", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(1)

        if user_dict.get("GOFILE_TOKEN", False):
            gftoken = user_dict["GOFILE_TOKEN"]
        elif Config.GOFILE_API:
            gftoken = Config.GOFILE_API
        else:
            gftoken = "None"

        if user_dict.get("GOFILE_FOLDER_ID", False):
            gffolder = user_dict["GOFILE_FOLDER_ID"]
        elif Config.GOFILE_FOLDER_ID:
            gffolder = Config.GOFILE_FOLDER_ID
        else:
            gffolder = "None (Uploads to Root)"

        text = f"""⌬ <b>Gofile Settings :</b>
┟ <b>Name</b> → {user_name}
┃
┠ <b>Gofile Token</b> → <code>{gftoken}</code>
┖ <b>Gofile Folder ID</b> → <code>{gffolder}</code>"""

    elif stype == "rclone":
        buttons.data_button("Rclone Config", f"userset {user_id} menu RCLONE_CONFIG")
        buttons.data_button(
            "Default Rclone Path", f"userset {user_id} menu RCLONE_PATH"
        )
        buttons.data_button("Rclone Flags", f"userset {user_id} menu RCLONE_FLAGS")

        buttons.data_button("Back", f"userset {user_id} back mirror", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")

        rccmsg = "Exists" if await aiopath.exists(rclone_conf) else "Not Exists"
        if user_dict.get("RCLONE_PATH", False):
            rccpath = user_dict["RCLONE_PATH"]
        elif Config.RCLONE_PATH:
            rccpath = Config.RCLONE_PATH
        else:
            rccpath = "None"
        btns = buttons.build_menu(1)

        if user_dict.get("RCLONE_FLAGS", False):
            rcflags = user_dict["RCLONE_FLAGS"]
        elif "RCLONE_FLAGS" not in user_dict and Config.RCLONE_FLAGS:
            rcflags = Config.RCLONE_FLAGS
        else:
            rcflags = "None"

        text = f"""⌬ <b>RClone Settings :</b>
┟ <b>Name</b> → {user_name}
┃
┠ <b>Rclone Config</b> → <b>{rccmsg}</b>
┠ <b>Rclone Flags</b> → <code>{rcflags}</code>
┖ <b>Rclone Path</b> → <code>{rccpath}</code>"""

    elif stype == "gdrive":
        buttons.data_button("token.pickle", f"userset {user_id} menu TOKEN_PICKLE")
        buttons.data_button("Default Gdrive ID", f"userset {user_id} menu GDRIVE_ID")
        buttons.data_button("Index URL", f"userset {user_id} menu INDEX_URL")
        if (
            user_dict.get("STOP_DUPLICATE", False)
            or "STOP_DUPLICATE" not in user_dict
            and Config.STOP_DUPLICATE
        ):
            buttons.data_button(
                "Disable Stop Duplicate", f"userset {user_id} tog STOP_DUPLICATE f"
            )
            sd_msg = "Enabled"
        else:
            buttons.data_button(
                "Enable Stop Duplicate",
                f"userset {user_id} tog STOP_DUPLICATE t",
                "l_body",
            )
            sd_msg = "Disabled"
        buttons.data_button("Back", f"userset {user_id} back mirror", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")

        tokenmsg = "Exists" if await aiopath.exists(token_pickle) else "Not Exists"
        if user_dict.get("GDRIVE_ID", False):
            gdrive_id = user_dict["GDRIVE_ID"]
        elif GDID := Config.GDRIVE_ID:
            gdrive_id = GDID
        else:
            gdrive_id = "None"
        index = user_dict["INDEX_URL"] if user_dict.get("INDEX_URL", False) else "None"
        btns = buttons.build_menu(2)

        text = f"""⌬ <b>GDrive Tools Settings :</b>
┟ <b>Name</b> → {user_name}
┃
┠ <b>Gdrive Token</b> → <b>{tokenmsg}</b>
┠ <b>Gdrive ID</b> → <code>{gdrive_id}</code>
┠ <b>Index URL</b> → <code>{index}</code>
┖ <b>Stop Duplicate</b> → <b>{sd_msg}</b>"""
    elif stype == "mirror":
        buttons.data_button("RClone Tools", f"userset {user_id} rclone")
        rccmsg = "Exists" if await aiopath.exists(rclone_conf) else "Not Exists"
        if user_dict.get("RCLONE_PATH", False):
            rccpath = user_dict["RCLONE_PATH"]
        elif RP := Config.RCLONE_PATH:
            rccpath = RP
        else:
            rccpath = "None"

        buttons.data_button("GDrive Tools", f"userset {user_id} gdrive")
        tokenmsg = "Exists" if await aiopath.exists(token_pickle) else "Not Exists"
        if user_dict.get("GDRIVE_ID", False):
            gdrive_id = user_dict["GDRIVE_ID"]
        elif GI := Config.GDRIVE_ID:
            gdrive_id = GI
        else:
            gdrive_id = "None"

        index = user_dict["INDEX_URL"] if user_dict.get("INDEX_URL", False) else "None"
        if (
            user_dict.get("STOP_DUPLICATE", False)
            or "STOP_DUPLICATE" not in user_dict
            and Config.STOP_DUPLICATE
        ):
            sd_msg = "Enabled"
        else:
            sd_msg = "Disabled"

        buttons.data_button("YT Up Tools", f"userset {user_id} yttools")
        buttons.data_button("Back", f"userset {user_id} back", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(1)

        text = f"""⌬ <b>Mirror Settings :</b>
┟ <b>Name</b> → {user_name}
┃
┠ <b>Rclone Config</b> → <b>{rccmsg}</b>
┠ <b>Rclone Path</b> → <code>{rccpath}</code>
┠ <b>Gdrive Token</b> → <b>{tokenmsg}</b>
┠ <b>Gdrive ID</b> → <code>{gdrive_id}</code>
┠ <b>Index Link</b> → <code>{index}</code>
┖ <b>Stop Duplicate</b> → <b>{sd_msg}</b>
"""

    elif stype == "ffset":
        buttons.data_button(
            "FFmpeg Cmds", f"userset {user_id} menu FFMPEG_CMDS", "header"
        )
        if user_dict.get("FFMPEG_CMDS", False):
            ffc = user_dict["FFMPEG_CMDS"]
        elif "FFMPEG_CMDS" not in user_dict and Config.FFMPEG_CMDS:
            ffc = Config.FFMPEG_CMDS
        else:
            ffc = "<b>Not Exists</b>"

        if isinstance(ffc, dict):
            ffc = "\n" + "\n".join(
                [
                    f"{no}. <b>{key}</b>: <code>{escape(str(value[0]))}</code>"
                    for no, (key, value) in enumerate(ffc.items(), start=1)
                ]
            )

        buttons.data_button("📝 Metadata (All Streams)", f"userset {user_id} menu METADATA")
        metadata_setting = user_dict.get("METADATA")
        display_meta_val = "<b>Not Set</b>"
        if isinstance(metadata_setting, dict) and metadata_setting:
            display_meta_val = ", ".join(
                f"{k}={escape(str(v))}" for k, v in metadata_setting.items()
            )
            display_meta_val = f"<code>{display_meta_val}</code>"
        elif isinstance(metadata_setting, str) and metadata_setting:  # Legacy
            display_meta_val = (
                f"<code>{escape(metadata_setting)}</code> [<i>Legacy, needs re-set</i>]"
            )

        buttons.data_button("🎵 Audio Metadata", f"userset {user_id} menu AUDIO_METADATA")
        audio_meta_setting = user_dict.get("AUDIO_METADATA")
        display_audio_meta = "<b>Not Set</b>"
        if isinstance(audio_meta_setting, dict) and audio_meta_setting:
            display_audio_meta = ", ".join(
                f"{k}={escape(str(v))}" for k, v in audio_meta_setting.items()
            )
            display_audio_meta = f"<code>{display_audio_meta}</code>"

        buttons.data_button("🎥 Video Metadata", f"userset {user_id} menu VIDEO_METADATA")
        video_meta_setting = user_dict.get("VIDEO_METADATA")
        display_video_meta = "<b>Not Set</b>"
        if isinstance(video_meta_setting, dict) and video_meta_setting:
            display_video_meta = ", ".join(
                f"{k}={escape(str(v))}" for k, v in video_meta_setting.items()
            )
            display_video_meta = f"<code>{display_video_meta}</code>"

        buttons.data_button(
            "💬 Subtitle Metadata", f"userset {user_id} menu SUBTITLE_METADATA"
        )
        subtitle_meta_setting = user_dict.get("SUBTITLE_METADATA")
        display_subtitle_meta = "<b>Not Set</b>"
        if isinstance(subtitle_meta_setting, dict) and subtitle_meta_setting:
            display_subtitle_meta = ", ".join(
                f"{k}={escape(str(v))}" for k, v in subtitle_meta_setting.items()
            )
            display_subtitle_meta = f"<code>{display_subtitle_meta}</code>"

        any_meta_set = any([
            isinstance(metadata_setting, (dict, str)) and metadata_setting,
            isinstance(audio_meta_setting, dict) and audio_meta_setting,
            isinstance(video_meta_setting, dict) and video_meta_setting,
            isinstance(subtitle_meta_setting, dict) and subtitle_meta_setting,
        ])
        if any_meta_set:
            buttons.data_button("🗑 Clear All Metadata", f"userset {user_id} clear_all_meta", "footer")
        buttons.data_button("Back", f"userset {user_id} back", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)

        text = f"""⌬ <b>FF Settings :</b>
┟ <b>Name</b> → {user_name}
┃
┠ <b>FFmpeg CLI Commands</b> → {ffc}
┃
┠ <b>📝 Metadata (All Streams)</b> → {display_meta_val}
┠ <b>🎵 Audio Metadata</b> → {display_audio_meta}
┠ <b>🎥 Video Metadata</b> → {display_video_meta}
┖ <b>💬 Subtitle Metadata</b> → {display_subtitle_meta}
┃
┖ <i>Tip: Send plain text as Metadata to auto-set title on ALL streams.</i>"""

    elif stype == "advanced":
        buttons.data_button(
            "Excluded Extensions", f"userset {user_id} menu EXCLUDED_EXTENSIONS"
        )
        if user_dict.get("EXCLUDED_EXTENSIONS", False):
            ex_ex = user_dict["EXCLUDED_EXTENSIONS"]
        elif "EXCLUDED_EXTENSIONS" not in user_dict:
            ex_ex = excluded_extensions
        else:
            ex_ex = "None"

        if ex_ex != "None":
            ex_ex = ", ".join(ex_ex)

        ns_msg = (
            f"<code>{swap}</code>"
            if (swap := user_dict.get("NAME_SWAP", False))
            else "<b>Not Exists</b>"
        )
        buttons.data_button("Name Swap", f"userset {user_id} menu NAME_SWAP")

        buttons.data_button("YT-DLP Options", f"userset {user_id} menu YT_DLP_OPTIONS")
        if user_dict.get("YT_DLP_OPTIONS", False):
            ytopt = user_dict["YT_DLP_OPTIONS"]
        elif "YT_DLP_OPTIONS" not in user_dict and Config.YT_DLP_OPTIONS:
            ytopt = Config.YT_DLP_OPTIONS
        else:
            ytopt = "None"

        upload_paths = user_dict.get("UPLOAD_PATHS", {})
        if not upload_paths and "UPLOAD_PATHS" not in user_dict and Config.UPLOAD_PATHS:
            upload_paths = Config.UPLOAD_PATHS
        else:
            upload_paths = "None"
        buttons.data_button("Upload Paths", f"userset {user_id} menu UPLOAD_PATHS")

        yt_cookie_path = f"cookies/{user_id}/cookies.txt"
        user_cookie_msg = (
            "Exists" if await aiopath.exists(yt_cookie_path) else "Not Exists"
        )
        buttons.data_button(
            "YT Cookie File", f"userset {user_id} menu USER_COOKIE_FILE"
        )

        buttons.data_button("Back", f"userset {user_id} back", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(1)

        text = f"""⌬ <b>Advanced Settings :</b>
┟ <b>Name</b> → {user_name}
┃
┠ <b>Name Swaps</b> → {ns_msg}
┠ <b>Excluded Extensions</b> → <code>{ex_ex}</code>
┠ <b>Upload Paths</b> → <b>{upload_paths}</b>
┠ <b>YT-DLP Options</b> → <code>{ytopt}</code>
┖ <b>YT User Cookie File</b> → <b>{user_cookie_msg}</b>"""
    elif stype == "yttools":
        buttons.data_button("YT Description", f"userset {user_id} menu YT_DESP")
        yt_desp_val = user_dict.get(
            "YT_DESP",
            Config.YT_DESP if hasattr(Config, "YT_DESP") else "Not Set (Uses Default)",
        )

        buttons.data_button("YT Tags", f"userset {user_id} menu YT_TAGS")
        yt_tags_val = user_dict.get(
            "YT_TAGS",
            Config.YT_TAGS if hasattr(Config, "YT_TAGS") else "Not Set (Uses Default)",
        )
        if isinstance(yt_tags_val, list):
            yt_tags_val = ",".join(yt_tags_val)

        buttons.data_button("YT Category ID", f"userset {user_id} menu YT_CATEGORY_ID")
        yt_cat_id_val = user_dict.get(
            "YT_CATEGORY_ID",
            (
                Config.YT_CATEGORY_ID
                if hasattr(Config, "YT_CATEGORY_ID")
                else "Not Set (Uses Default)"
            ),
        )

        buttons.data_button(
            "YT Privacy Status", f"userset {user_id} menu YT_PRIVACY_STATUS"
        )
        yt_privacy_val = user_dict.get(
            "YT_PRIVACY_STATUS",
            (
                Config.YT_PRIVACY_STATUS
                if hasattr(Config, "YT_PRIVACY_STATUS")
                else "Not Set (Uses Default)"
            ),
        )

        buttons.data_button("Back", f"userset {user_id} back mirror", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)

        text = f"""⌬ <b>YouTube Tools Settings:</b>
┟ <b>Name</b> → {user_name}
┃
┠ <b>YT Description</b> → <code>{escape(str(yt_desp_val))}</code>
┠ <b>YT Tags</b> → <code>{escape(str(yt_tags_val))}</code>
┠ <b>YT Category ID</b> → <code>{escape(str(yt_cat_id_val))}</code>
┖ <b>YT Privacy Status</b> → <code>{escape(str(yt_privacy_val))}</code>"""

    # ── Video Tools ──
    elif stype == "vidtools":
        for key, label in VID_MODE.items():
            icon = _VID_ICONS.get(key, "🎬")
            buttons.data_button(f"{icon} {label}", f"userset {user_id} vid_setting {key}")
        buttons.data_button("« Back",  f"userset {user_id} back",  "footer")
        buttons.data_button("✘ Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)
        text = (
            f"⌬ <b>Video Tools :</b> {user_name}\n"
            f"┟\n"
            f"┖ <b>Total Tools :</b> <i>{len(VID_MODE)}</i>\n\n"
            f"<i>Choose a video tool below to view and manage its settings.</i>"
        )

    # ── Merge Videos ──
    elif stype == "vid_merge":
        is_enabled = "vid_vid" not in set(user_dict.get("disabled_vidtools", []))
        merge_mode = user_dict.get("vid_merge_mode") or _VID_DEFAULTS["vid_merge_mode"]
        buttons.data_button(
            f'{"❌ Disable" if is_enabled else "✅ Enable"} Tool',
            f"userset {user_id} toggle_vid vid_vid")
        buttons.data_button(
            f"Merge Mode : {merge_mode.title()}",
            f"userset {user_id} vid_cycle vid_merge_mode")
        buttons.data_button("« Back",  f"userset {user_id} vidtools", "footer")
        buttons.data_button("✘ Close", f"userset {user_id} close",   "footer")
        btns = buttons.build_menu(2)
        text = (
            f"⌬ <b>Merge Videos :</b> {user_name}\n"
            f"┟\n"
            f"┠ <b>Status :</b> <i>{'Enabled ✅' if is_enabled else 'Disabled ❌'}</i>\n"
            f"┖ <b>Merge Mode :</b> <i>{merge_mode.title()}</i>\n\n"
            f"<i>Merge multiple videos. Sequential = play one after another, "
            f"Concat = ffmpeg concat demuxer (faster, same codec required).</i>"
        )

    # ── Audio Mux ──
    elif stype == "vid_audmux":
        is_enabled  = "vid_aud" not in set(user_dict.get("disabled_vidtools", []))
        audio_lang  = user_dict.get("vid_audio_lang") or "Auto"
        audio_codec = user_dict.get("vid_audio_codec") or _VID_DEFAULTS["vid_audio_codec"]
        has_lang    = bool(user_dict.get("vid_audio_lang"))
        buttons.data_button(
            f'{"❌ Disable" if is_enabled else "✅ Enable"} Tool',
            f"userset {user_id} toggle_vid vid_aud")
        buttons.data_button(
            f'{"✅ " if has_lang else ""}Audio Language',
            f"userset {user_id} vid_settext vid_audio_lang")
        if has_lang:
            buttons.data_button("🗑️ Reset Language", f"userset {user_id} rem_vid vid_audio_lang")
        buttons.data_button(
            f"Audio Codec : {audio_codec.upper()}",
            f"userset {user_id} vid_cycle vid_audio_codec")
        buttons.data_button("« Back",  f"userset {user_id} vidtools", "footer")
        buttons.data_button("✘ Close", f"userset {user_id} close",   "footer")
        btns = buttons.build_menu(2)
        text = (
            f"⌬ <b>Merge Audio Tracks :</b> {user_name}\n"
            f"┟\n"
            f"┠ <b>Status :</b> <i>{'Enabled ✅' if is_enabled else 'Disabled ❌'}</i>\n"
            f"┠ <b>Audio Language :</b> <code>{audio_lang}</code>\n"
            f"┖ <b>Audio Codec :</b> <i>{audio_codec.upper()}</i>\n\n"
            f"<i>Mux external audio into your video. Set ISO 639 language code "
            f"(e.g. <code>eng</code>, <code>hin</code>) and target codec.</i>"
        )

    # ── Hardsub ──
    elif stype == "vid_hardsub":
        is_enabled = "vid_sub" not in set(user_dict.get("disabled_vidtools", []))
        has_font   = bool(user_dict.get("vid_hardsub_font"))
        has_size   = bool(user_dict.get("vid_hardsub_size"))
        hs_font    = user_dict.get("vid_hardsub_font") or getattr(Config, "VT_HARDSUB_FONT_NAME", None) or "Arial"
        hs_size    = user_dict.get("vid_hardsub_size") or getattr(Config, "VT_HARDSUB_FONT_SIZE", None) or "Default"
        buttons.data_button(
            f'{"❌ Disable" if is_enabled else "✅ Enable"} Tool',
            f"userset {user_id} toggle_vid vid_sub")
        buttons.data_button(
            f'{"✅ " if has_font else ""}HardSub Font',
            f"userset {user_id} vid_settext vid_hardsub_font")
        if has_font:
            buttons.data_button("🗑️ Reset Font", f"userset {user_id} rem_vid vid_hardsub_font")
        buttons.data_button(
            f'{"✅ " if has_size else ""}Font Size',
            f"userset {user_id} vid_settext vid_hardsub_size")
        if has_size:
            buttons.data_button("🗑️ Reset Size", f"userset {user_id} rem_vid vid_hardsub_size")
        buttons.data_button("« Back",  f"userset {user_id} vidtools", "footer")
        buttons.data_button("✘ Close", f"userset {user_id} close",   "footer")
        btns = buttons.build_menu(2)
        text = (
            f"⌬ <b>Merge Subtitles :</b> {user_name}\n"
            f"┟\n"
            f"┠ <b>Status :</b> <i>{'Enabled ✅' if is_enabled else 'Disabled ❌'}</i>\n"
            f"┠ <b>Font :</b> <code>{hs_font}</code>\n"
            f"┖ <b>Font Size :</b> <code>{hs_size}</code>\n\n"
            f"<i>Hardcode (burn-in) subtitle files permanently into your video stream.</i>"
        )

    # ── SubSync ──
    elif stype == "vid_subsync":
        is_enabled = "subsync" not in set(user_dict.get("disabled_vidtools", []))
        has_delay  = bool(user_dict.get("vid_subsync_delay"))
        delay      = user_dict.get("vid_subsync_delay") or _VID_DEFAULTS["vid_subsync_delay"]
        buttons.data_button(
            f'{"❌ Disable" if is_enabled else "✅ Enable"} Tool',
            f"userset {user_id} toggle_vid subsync")
        buttons.data_button(
            f'{"✅ " if has_delay else ""}Sync Delay (ms)',
            f"userset {user_id} vid_settext vid_subsync_delay")
        if has_delay:
            buttons.data_button("🗑️ Reset Delay", f"userset {user_id} rem_vid vid_subsync_delay")
        buttons.data_button("« Back",  f"userset {user_id} vidtools", "footer")
        buttons.data_button("✘ Close", f"userset {user_id} close",   "footer")
        btns = buttons.build_menu(2)
        text = (
            f"⌬ <b>Subtitle Sync :</b> {user_name}\n"
            f"┟\n"
            f"┠ <b>Status :</b> <i>{'Enabled ✅' if is_enabled else 'Disabled ❌'}</i>\n"
            f"┖ <b>Sync Delay :</b> <code>{delay} ms</code>\n\n"
            f"<i>Adjust subtitle timing. Positive delays subs, negative advances them. "
            f"Example: <code>-500</code> = 500ms earlier.</i>"
        )

    # ── Compress ──
    elif stype == "vid_compress":
        vid_264    = user_dict.get("vid_264_preset") or getattr(Config, "VT_LIB264_PRESET", None) or "fast"
        vid_265    = user_dict.get("vid_265_preset") or getattr(Config, "VT_LIB265_PRESET", None) or "slow"
        has_banner = bool(user_dict.get("vid_banner"))
        vid_banner = user_dict.get("vid_banner") or getattr(Config, "VT_COMPRESS_BANNER", None) or "Not Set"
        for p in _COMPRESS_PRESETS:
            mark = "🔥 " if p == vid_264 else ""
            buttons.data_button(f"{mark}264:{p}", f"userset {user_id} vid_set vid_264_preset {p}")
        for p in _COMPRESS_PRESETS:
            mark = "🔥 " if p == vid_265 else ""
            buttons.data_button(f"{mark}265:{p}", f"userset {user_id} vid_set vid_265_preset {p}")
        buttons.data_button(
            f'{"✅ " if has_banner else ""}Compress Banner',
            f"userset {user_id} vid_settext vid_banner")
        if has_banner:
            buttons.data_button("🗑️ Reset Banner", f"userset {user_id} rem_vid vid_banner")
        buttons.data_button("« Back",  f"userset {user_id} vidtools", "footer")
        buttons.data_button("✘ Close", f"userset {user_id} close",   "footer")
        btns = buttons.build_menu(3)
        text = (
            f"⌬ <b>Compress Video :</b> {user_name}\n"
            f"┟\n"
            f"┠ <b>x264 Preset :</b> <i>{vid_264}</i>\n"
            f"┠ <b>x265 Preset :</b> <i>{vid_265}</i>\n"
            f"┖ <b>Banner :</b> <code>{escape(str(vid_banner))}</code>\n\n"
            f"<i>Re-encode videos using x264 or x265. Tap a preset to set it as default.</i>"
        )

    # ── Convert ──
    elif stype == "vid_convert":
        is_enabled = "convert" not in set(user_dict.get("disabled_vidtools", []))
        fmt        = user_dict.get("vid_convert_format") or _VID_DEFAULTS["vid_convert_format"]
        buttons.data_button(
            f'{"❌ Disable" if is_enabled else "✅ Enable"} Tool',
            f"userset {user_id} toggle_vid convert")
        for f in _VID_FIELD_OPTIONS["vid_convert_format"]:
            mark = "🔥 " if f == fmt else ""
            buttons.data_button(f"{mark}{f.upper()}", f"userset {user_id} vid_set vid_convert_format {f}")
        buttons.data_button("« Back",  f"userset {user_id} vidtools", "footer")
        buttons.data_button("✘ Close", f"userset {user_id} close",   "footer")
        btns = buttons.build_menu(3)
        text = (
            f"⌬ <b>Convert Format :</b> {user_name}\n"
            f"┟\n"
            f"┠ <b>Status :</b> <i>{'Enabled ✅' if is_enabled else 'Disabled ❌'}</i>\n"
            f"┖ <b>Output Format :</b> <i>{fmt.upper()}</i>\n\n"
            f"<i>Convert videos between container formats. Tap a format to set it as default.</i>"
        )

    # ── Watermark ──
    elif stype == "vid_watermark":
        is_enabled = "watermark" not in set(user_dict.get("disabled_vidtools", []))
        has_text   = bool(user_dict.get("vid_watermark_text"))
        has_opa    = bool(user_dict.get("vid_watermark_opacity"))
        wm_text    = user_dict.get("vid_watermark_text")    or "Not Set"
        wm_pos     = user_dict.get("vid_watermark_pos")     or _VID_DEFAULTS["vid_watermark_pos"]
        wm_opa     = user_dict.get("vid_watermark_opacity") or _VID_DEFAULTS["vid_watermark_opacity"]
        buttons.data_button(
            f'{"❌ Disable" if is_enabled else "✅ Enable"} Tool',
            f"userset {user_id} toggle_vid watermark")
        buttons.data_button(
            f'{"✅ " if has_text else ""}Watermark Text',
            f"userset {user_id} vid_settext vid_watermark_text")
        if has_text:
            buttons.data_button("🗑️ Reset Text", f"userset {user_id} rem_vid vid_watermark_text")
        buttons.data_button(
            f"Position : {wm_pos.title()}",
            f"userset {user_id} vid_cycle vid_watermark_pos")
        buttons.data_button(
            f'{"✅ " if has_opa else ""}Opacity (%)',
            f"userset {user_id} vid_settext vid_watermark_opacity")
        if has_opa:
            buttons.data_button("🗑️ Reset Opacity", f"userset {user_id} rem_vid vid_watermark_opacity")
        buttons.data_button("« Back",  f"userset {user_id} vidtools", "footer")
        buttons.data_button("✘ Close", f"userset {user_id} close",   "footer")
        btns = buttons.build_menu(2)
        text = (
            f"⌬ <b>Add Watermark :</b> {user_name}\n"
            f"┟\n"
            f"┠ <b>Status :</b> <i>{'Enabled ✅' if is_enabled else 'Disabled ❌'}</i>\n"
            f"┠ <b>Text :</b> <code>{wm_text}</code>\n"
            f"┠ <b>Position :</b> <i>{wm_pos.title()}</i>\n"
            f"┖ <b>Opacity :</b> <i>{wm_opa}%</i>\n\n"
            f"<i>Apply text watermark on output videos. Set position and opacity (0–100).</i>"
        )

    # ── Extract ──
    elif stype == "vid_extract":
        is_enabled = "extract" not in set(user_dict.get("disabled_vidtools", []))
        selected   = user_dict.get("vid_extract_streams", _VID_DEFAULTS["vid_extract_streams"])
        buttons.data_button(
            f'{"❌ Disable" if is_enabled else "✅ Enable"} Tool',
            f"userset {user_id} toggle_vid extract")
        for stream in _VID_MULTI_OPTIONS["vid_extract_streams"]:
            mark = "✅" if stream in selected else "❌"
            buttons.data_button(
                f"{mark} {stream.title()}",
                f"userset {user_id} vid_multi vid_extract_streams {stream}")
        buttons.data_button("« Back",  f"userset {user_id} vidtools", "footer")
        buttons.data_button("✘ Close", f"userset {user_id} close",   "footer")
        btns = buttons.build_menu(2)
        text = (
            f"⌬ <b>Extract Stream :</b> {user_name}\n"
            f"┟\n"
            f"┠ <b>Status :</b> <i>{'Enabled ✅' if is_enabled else 'Disabled ❌'}</i>\n"
            f"┖ <b>Extract :</b> <i>{', '.join(s.title() for s in selected) or 'None'}</i>\n\n"
            f"<i>Toggle which stream types to extract from the source media file.</i>"
        )

    # ── Trim ──
    elif stype == "vid_trim":
        is_enabled = "trim" not in set(user_dict.get("disabled_vidtools", []))
        has_start  = bool(user_dict.get("vid_trim_start"))
        has_end    = bool(user_dict.get("vid_trim_end"))
        t_start    = user_dict.get("vid_trim_start") or _VID_DEFAULTS["vid_trim_start"]
        t_end      = user_dict.get("vid_trim_end")   or _VID_DEFAULTS["vid_trim_end"]
        buttons.data_button(
            f'{"❌ Disable" if is_enabled else "✅ Enable"} Tool',
            f"userset {user_id} toggle_vid trim")
        buttons.data_button(
            f'{"✅ " if has_start else ""}Start Time',
            f"userset {user_id} vid_settext vid_trim_start")
        if has_start:
            buttons.data_button("🗑️ Reset Start", f"userset {user_id} rem_vid vid_trim_start")
        buttons.data_button(
            f'{"✅ " if has_end else ""}End Time',
            f"userset {user_id} vid_settext vid_trim_end")
        if has_end:
            buttons.data_button("🗑️ Reset End", f"userset {user_id} rem_vid vid_trim_end")
        buttons.data_button("« Back",  f"userset {user_id} vidtools", "footer")
        buttons.data_button("✘ Close", f"userset {user_id} close",   "footer")
        btns = buttons.build_menu(2)
        text = (
            f"⌬ <b>Trim Video :</b> {user_name}\n"
            f"┟\n"
            f"┠ <b>Status :</b> <i>{'Enabled ✅' if is_enabled else 'Disabled ❌'}</i>\n"
            f"┠ <b>Start :</b> <code>{t_start}</code>\n"
            f"┖ <b>End :</b> <code>{t_end}</code>\n\n"
            f"<i>Trim videos using HH:MM:SS. Example start: <code>00:01:30</code>, end: <code>00:05:00</code>.</i>"
        )

    # ── Remove Stream ──
    elif stype == "vid_rmstream":
        is_enabled = "rmstream" not in set(user_dict.get("disabled_vidtools", []))
        selected   = user_dict.get("vid_rmstream_kind", _VID_DEFAULTS["vid_rmstream_kind"])
        buttons.data_button(
            f'{"❌ Disable" if is_enabled else "✅ Enable"} Tool',
            f"userset {user_id} toggle_vid rmstream")
        for stream in _VID_MULTI_OPTIONS["vid_rmstream_kind"]:
            mark = "✅" if stream in selected else "❌"
            buttons.data_button(
                f"{mark} Remove {stream.title()}",
                f"userset {user_id} vid_multi vid_rmstream_kind {stream}")
        buttons.data_button("« Back",  f"userset {user_id} vidtools", "footer")
        buttons.data_button("✘ Close", f"userset {user_id} close",   "footer")
        btns = buttons.build_menu(2)
        text = (
            f"⌬ <b>Remove Stream :</b> {user_name}\n"
            f"┟\n"
            f"┠ <b>Status :</b> <i>{'Enabled ✅' if is_enabled else 'Disabled ❌'}</i>\n"
            f"┖ <b>Removing :</b> <i>{', '.join(s.title() for s in selected) or 'None'}</i>\n\n"
            f"<i>Toggle which stream types to strip from the output video.</i>"
        )

    return text, btns


async def update_user_settings(query, stype="main"):
    handler_dict[query.from_user.id] = False
    msg, button = await get_user_settings(query.from_user, stype)
    await edit_message(query.message, msg, button)


@new_task
async def send_user_settings(_, message):
    from_user = message.from_user
    handler_dict[from_user.id] = False
    msg, button = await get_user_settings(from_user)
    await send_message(message, msg, button)


@new_task
async def add_file(_, message, ftype, rfunc):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    if ftype == "THUMBNAIL":
        des_dir = await create_thumb(message, user_id)
    elif ftype == "RCLONE_CONFIG":
        rpath = f"{getcwd()}/rclone/"
        await makedirs(rpath, exist_ok=True)
        des_dir = f"{rpath}{user_id}.conf"
        await message.download(file_name=des_dir)
    elif ftype == "TOKEN_PICKLE":
        tpath = f"{getcwd()}/tokens/"
        await makedirs(tpath, exist_ok=True)
        des_dir = f"{tpath}{user_id}.pickle"
        await message.download(file_name=des_dir)
    elif ftype == "USER_COOKIE_FILE":
        cpath = f"{getcwd()}/cookies/{user_id}"
        await makedirs(cpath, exist_ok=True)
        des_dir = f"{cpath}/cookies.txt"
        await message.download(file_name=des_dir)
    await delete_message(message)
    update_user_ldata(user_id, ftype, des_dir)
    await rfunc()
    await database.update_user_doc(user_id, ftype, des_dir)


@new_task
async def add_one(_, message, option, rfunc):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    user_dict = user_data.get(user_id, {})
    value = message.text
    if value.startswith("{") and value.endswith("}"):
        try:
            value = eval(value)
            if user_dict[option]:
                user_dict[option].update(value)
            else:
                update_user_ldata(user_id, option, value)
        except Exception as e:
            await send_message(message, str(e))
            return
    else:
        await send_message(message, "It must be Dict!")
        return
    await delete_message(message)
    await rfunc()
    await database.update_user_data(user_id)


@new_task
async def remove_one(_, message, option, rfunc):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    user_dict = user_data.get(user_id, {})
    names = message.text.split("/")
    for name in names:
        if name in user_dict[option]:
            del user_dict[option][name]
    await delete_message(message)
    await rfunc()
    await database.update_user_data(user_id)


@new_task
async def set_option(_, message, option, rfunc):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    value = message.text
    if option == "LEECH_SPLIT_SIZE":
        if not value.isdigit():
            value = get_size_bytes(value)
        value = min(int(value), TgClient.MAX_SPLIT_SIZE)
    elif option == "LEECH_DUMP_CHAT":
        value = value.strip()
        if value.lower() == "pm":
            pass  # keep as string "pm", common.py handles it
        elif value.lstrip("-").isdigit():
            value = int(value)
        # else keep as-is (username, b:/u:/h: prefix, topic pipe notation etc.)
    elif option == "EXCLUDED_EXTENSIONS":
        fx = value.split()
        value = ["aria2", "!qB"]
        for x in fx:
            x = x.lstrip(".")
            value.append(x.strip().lower())
    elif option == "YT_TAGS":
        if isinstance(value, str):
            value = [tag.strip() for tag in value.split(",") if tag.strip()]
        elif not isinstance(value, list):
            await send_message(message, "YT Tags must be a comma-separated string.")
            return
    elif option == "YT_CATEGORY_ID":
        if isinstance(value, str) and value.isdigit():
            value = int(value)
        elif not isinstance(value, int):
            await send_message(message, "YT Category ID must be a whole number.")
            return
    elif option == "YT_PRIVACY_STATUS":
        allowed_statuses = ["public", "private", "unlisted"]
        if not isinstance(value, str) or value.lower() not in allowed_statuses:
            await send_message(
                message,
                f"YT Privacy Status must be one of: {', '.join(allowed_statuses)}.",
            )
            return
        value = value.lower()
    elif option in [
        "METADATA",
        "AUDIO_METADATA",
        "VIDEO_METADATA",
        "SUBTITLE_METADATA",
    ]:
        parsed_metadata_dict = {}
        if value and isinstance(value, str):
            if value.strip() == "":
                value = {}
            elif "=" not in value:
                # Plain text — treat as title for ALL streams
                parsed_metadata_dict = {"title": value.strip()}
                if option == "METADATA":
                    for _stream_key in ["AUDIO_METADATA", "VIDEO_METADATA", "SUBTITLE_METADATA"]:
                        update_user_ldata(user_id, _stream_key, dict(parsed_metadata_dict))
                value = parsed_metadata_dict
            else:
                parts = []
                current = ""
                i = 0
                while i < len(value):
                    if value[i] == "\\" and i + 1 < len(value) and value[i + 1] == "|":
                        current += "|"
                        i += 2
                    elif value[i] == "|":
                        parts.append(current)
                        current = ""
                        i += 1
                    else:
                        current += value[i]
                        i += 1
                if current:
                    parts.append(current)

                for part in parts:
                    if "=" in part:
                        key, val_str = part.split("=", 1)
                        parsed_metadata_dict[key.strip()] = val_str.strip()
                if not parsed_metadata_dict and value.strip() != "":
                    await send_message(
                        message,
                        "Malformed metadata string. Format: key1=value1|key2=value2. Use \\| to escape pipe characters.\n\n<i>Tip: To set a plain title on all streams, just send text without any <code>=</code> sign.</i>",
                    )
                    return
                value = parsed_metadata_dict
        else:
            value = {}

    elif option in ["UPLOAD_PATHS", "FFMPEG_CMDS", "YT_DLP_OPTIONS"]:
        if value.startswith("{") and value.endswith("}"):
            try:
                value = eval(sub(r"\s+", " ", value))
            except Exception as e:
                await send_message(message, str(e))
                return
        else:
            await send_message(message, "It must be dict!")
            return
    update_user_ldata(user_id, option, value)
    await delete_message(message)
    await rfunc()
    await database.update_user_data(user_id)


async def get_menu(option, message, user_id):
    handler_dict[user_id] = False
    user_dict = user_data.get(user_id, {})

    file_dict = {
        "THUMBNAIL": f"thumbnails/{user_id}.jpg",
        "RCLONE_CONFIG": f"rclone/{user_id}.conf",
        "TOKEN_PICKLE": f"tokens/{user_id}.pickle",
        "USER_COOKIE_FILE": f"cookies/{user_id}/cookies.txt",
    }

    buttons = ButtonMaker()
    if option in ["THUMBNAIL", "RCLONE_CONFIG", "TOKEN_PICKLE", "USER_COOKIE_FILE"]:
        key = "file"
    else:
        key = "set"
    buttons.data_button(
        "Change" if user_dict.get(option, False) else "Set",
        f"userset {user_id} {key} {option}",
    )
    if user_dict.get(option, False):
        if option == "THUMBNAIL":
            buttons.data_button(
                "View Thumb", f"userset {user_id} view THUMBNAIL", "header"
            )
        elif option in ["YT_DLP_OPTIONS", "FFMPEG_CMDS", "UPLOAD_PATHS"]:
            buttons.data_button(
                "Add One", f"userset {user_id} addone {option}", "header"
            )
            buttons.data_button(
                "Remove One", f"userset {user_id} rmone {option}", "header"
            )

        if key != "file":  # TODO: option default val check
            buttons.data_button("Reset", f"userset {user_id} reset {option}")
        elif await aiopath.exists(file_dict[option]):
            buttons.data_button("Remove", f"userset {user_id} remove {option}")
    if option in leech_options:
        back_to = "leech"
    elif option in rclone_options:
        back_to = "rclone"
    elif option in gdrive_options:
        back_to = "gdrive"
    elif option in yt_options:
        back_to = "yttools"
    elif option in ffset_options:
        back_to = "ffset"
    elif option in advanced_options:
        back_to = "advanced"
    else:
        back_to = "back"
    buttons.data_button("Back", f"userset {user_id} {back_to}", "footer")
    buttons.data_button("Close", f"userset {user_id} close", "footer")
    val = user_dict.get(option)
    if option in file_dict and await aiopath.exists(file_dict[option]):
        val = "<b>Exists</b>"
    elif option == "LEECH_SPLIT_SIZE":
        val = get_readable_file_size(val)
    elif option == "METADATA":
        current_meta_val = user_dict.get(option)
        if isinstance(current_meta_val, dict) and current_meta_val:
            val = ", ".join(
                f"{k}={escape(str(v))}" for k, v in current_meta_val.items()
            )
            val = f"<code>{val}</code>"
        elif isinstance(current_meta_val, str) and current_meta_val:
            val = (
                f"<code>{escape(current_meta_val)}</code> [<i>Legacy, needs re-set</i>]"
            )
        elif not current_meta_val:
            val = "<b>Not Set</b>"

        if val is None:
            val = "<b>Not Exists</b>"

    if option == "METADATA":
        text = f"""⌬ <b><u>Menu Settings :</u></b>
│
┟ <b>Option</b> → {option}
┃
┠ <b>Option's Value</b> → {val if val else "<b>Not Exists</b>"}
┃
┠ <b>Default Input Type</b> → {user_settings_text[option][0]}
┠ <b>Description</b> → {user_settings_text[option][1]}
┃
┠ <b>Dynamic Variables:</b>
┠ • <code>{{filename}}</code> - Full filename
┠ • <code>{{basename}}</code> - Filename without extension  
┠ • <code>{{extension}}</code> - File extension
┃
┠ • <code>{{audiolang}}</code> - Audio language
┖ • <code>{{sublang}}</code> - Subtitle language
"""
    else:
        text = f"""⌬ <b><u>Menu Settings :</u></b>
│
┟ <b>Option</b> → {option}
┃
┠ <b>Option's Value</b> → {val if val else "<b>Not Exists</b>"}
┃
┠ <b>Default Input Type</b> → {user_settings_text[option][0]}
┖ <b>Description</b> → {user_settings_text[option][1]}
"""
    await edit_message(message, text, buttons.build_menu(2))


@new_task
async def set_vid_text_option(_, message, field, rfunc):
    user_id = message.from_user.id
    if not handler_dict.get(user_id, False):
        return
    handler_dict[user_id] = False
    value = message.text.strip() if message.text else ""
    if value:
        if field == "vid_hardsub_size" and value.isdigit():
            value = int(value)
        update_user_ldata(user_id, field, value)
        await database.update_user_data(user_id)
    await delete_message(message)
    await rfunc()


async def event_handler(client, query, pfunc, rfunc, photo=False, document=False):
    user_id = query.from_user.id
    handler_dict[user_id] = True
    start_time = update_time = time()

    async def event_filter(_, __, event):
        if photo:
            mtype = event.photo or event.document
        elif document:
            mtype = event.document
        else:
            mtype = event.text
        user = event.from_user or event.sender_chat
        return bool(
            user.id == user_id and event.chat.id == query.message.chat.id and mtype
        )

    handler = client.add_handler(
        MessageHandler(pfunc, filters=create(event_filter)), group=-1
    )

    while handler_dict[user_id]:
        await sleep(0.5)
        if time() - start_time > 60:
            handler_dict[user_id] = False
            await rfunc()
        elif time() - update_time > 8 and handler_dict[user_id]:
            update_time = time()
            msg = await client.get_messages(query.message.chat.id, query.message.id)
            text = msg.text.split("\n")
            text[-1] = (
                f"┖ <b>Time Left :</b> <code>{round(60 - (time() - start_time), 2)} sec</code>"
            )
            await edit_message(msg, "\n".join(text), msg.reply_markup)
    client.remove_handler(*handler)


@new_task
async def edit_user_settings(client, query):
    from_user = query.from_user
    user_id = from_user.id
    name = from_user.mention
    message = query.message
    data = query.data.split()

    handler_dict[user_id] = False
    thumb_path = f"thumbnails/{user_id}.jpg"
    rclone_conf = f"rclone/{user_id}.conf"
    token_pickle = f"tokens/{user_id}.pickle"
    yt_cookie_path = f"cookies/{user_id}/cookies.txt"

    user_dict = user_data.get(user_id, {})
    if user_id != int(data[1]):
        return await query.answer("Not Yours!", show_alert=True)
    elif data[2] == "setevent":
        await query.answer()
    elif data[2] in [
        "general",
        "mirror",
        "leech",
        "uphoster",
        "gofile",
        "buzzheavier",
        "pixeldrain",
        "ffset",
        "advanced",
        "gdrive",
        "rclone",
    ]:
        await query.answer()
        await update_user_settings(query, data[2])
    elif data[2] == "yttools":
        await query.answer()
        await update_user_settings(query, data[2])
    elif data[2] == "uphoster_destinations":
        await query.answer()
        user_dict = user_data.get(user_id, {})
        uphoster_service = user_dict.get("UPHOSTER_SERVICE", "gofile")
        selected_services = uphoster_service.split(",") if uphoster_service else []

        if len(data) > 3:
            service = data[3]
            if service in selected_services:
                if len(selected_services) > 1:
                    selected_services.remove(service)
                else:
                    await query.answer(
                        "At least one destination must be selected!", show_alert=True
                    )
            else:
                selected_services.append(service)
            new_services = ",".join(selected_services)
            update_user_ldata(user_id, "UPHOSTER_SERVICE", new_services)
            await database.update_user_data(user_id)
            selected_services = new_services.split(",")
        else:
            selected_services = (
                uphoster_service.split(",") if uphoster_service else ["gofile"]
            )

        buttons = ButtonMaker()
        for service in ["gofile", "buzzheavier", "pixeldrain"]:
            state = "✓" if service in selected_services else ""
            buttons.data_button(
                f"{service.capitalize()} {state}",
                f"userset {user_id} uphoster_destinations {service}",
            )

        buttons.data_button("Back", f"userset {user_id} back uphoster", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")

        text = f"""⌬ <b>Select Uphoster Destinations :</b>"""
        await edit_message(message, text, buttons.build_menu(1))
    elif data[2] == "menu":
        await query.answer()
        await get_menu(data[3], message, user_id)
    elif data[2] == "tog":
        await query.answer()
        update_user_ldata(user_id, data[3], data[4] == "t")
        if data[3] == "STOP_DUPLICATE":
            back_to = "gdrive"
        elif data[3] in ["USER_TOKENS", "USE_DEFAULT_COOKIE"]:
            back_to = "general"
        else:
            back_to = "leech"
        await update_user_settings(query, stype=back_to)
        await database.update_user_data(user_id)
    elif data[2] == "file":
        await query.answer()
        buttons = ButtonMaker()
        text = user_settings_text[data[3]][2]
        buttons.data_button("Stop", f"userset {user_id} menu {data[3]} stop")
        buttons.data_button("Back", f"userset {user_id} menu {data[3]}", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        prompt_title = data[3].replace("_", " ").title()
        new_message_text = f"⌬ <b>Set {prompt_title}</b>\n\n{text}"
        await edit_message(message, new_message_text, buttons.build_menu(1))
        rfunc = partial(get_menu, data[3], message, user_id)
        pfunc = partial(add_file, ftype=data[3], rfunc=rfunc)
        await event_handler(
            client,
            query,
            pfunc,
            rfunc,
            photo=data[3] == "THUMBNAIL",
            document=data[3] != "THUMBNAIL",
        )
    elif data[2] in ["set", "addone", "rmone"]:
        await query.answer()
        buttons = ButtonMaker()
        if data[2] == "set":
            text = user_settings_text[data[3]][2]
            func = set_option
        elif data[2] == "addone":
            text = f"Add one or more string key and value to {data[3]}. Example: {{'key 1': 62625261, 'key 2': 'value 2'}}. Timeout: 60 sec"
            func = add_one
        elif data[2] == "rmone":
            text = f"Remove one or more key from {data[3]}. Example: key 1/key2/key 3. Timeout: 60 sec"
            func = remove_one
        buttons.data_button("Stop", f"userset {user_id} menu {data[3]} stop")
        buttons.data_button("Back", f"userset {user_id} menu {data[3]}", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        await edit_message(
            message, message.text.html + "\n\n" + text, buttons.build_menu(1)
        )
        rfunc = partial(get_menu, data[3], message, user_id)
        pfunc = partial(func, option=data[3], rfunc=rfunc)
        await event_handler(client, query, pfunc, rfunc)
    elif data[2] == "remove":
        await query.answer("Removed!", show_alert=True)
        if data[3] in [
            "THUMBNAIL",
            "RCLONE_CONFIG",
            "TOKEN_PICKLE",
            "USER_COOKIE_FILE",
        ]:
            if data[3] == "THUMBNAIL":
                fpath = thumb_path
            elif data[3] == "RCLONE_CONFIG":
                fpath = rclone_conf
            elif data[3] == "USER_COOKIE_FILE":
                fpath = yt_cookie_path
            else:
                fpath = token_pickle
            if await aiopath.exists(fpath):
                await remove(fpath)
            del user_dict[data[3]]
            await database.update_user_doc(user_id, data[3])
        else:
            update_user_ldata(user_id, data[3], "")
            await database.update_user_data(user_id)
        await get_menu(data[3], message, user_id)
    elif data[2] == "reset":
        await query.answer("Reset Done!", show_alert=True)
        user_dict.pop(data[3], None)
        await database.update_user_data(user_id)
        await get_menu(data[3], message, user_id)
    elif data[2] == "confirm_reset_all":
        await query.answer()
        buttons = ButtonMaker()
        buttons.data_button("Yes", f"userset {user_id} do_reset_all yes")
        buttons.data_button("No", f"userset {user_id} do_reset_all no")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        text = "<i>Are you sure you want to reset all your user settings?</i>"
        await edit_message(query.message, text, buttons.build_menu(2))
    elif data[2] == "do_reset_all":
        if data[3] == "yes":
            await query.answer("Reset Done!", show_alert=True)
            user_dict = user_data.get(user_id, {})
            for k in list(user_dict.keys()):
                if k not in ("SUDO", "AUTH", "VERIFY_TOKEN", "VERIFY_TIME"):
                    del user_dict[k]
            for fpath in [thumb_path, rclone_conf, token_pickle, yt_cookie_path]:
                if await aiopath.exists(fpath):
                    await remove(fpath)
            await update_user_settings(query)
            await database.update_user_data(user_id)
        else:
            await query.answer("Reset Cancelled.", show_alert=True)
            await update_user_settings(query)
    elif data[2] == "view":
        await query.answer()
        await send_file(message, thumb_path, name)
    elif data[2] == "clear_all_meta":
        await query.answer("All metadata cleared!", show_alert=True)
        _live_dict = user_data.get(user_id, {})
        for _mk in ["METADATA", "AUDIO_METADATA", "VIDEO_METADATA", "SUBTITLE_METADATA"]:
            _live_dict.pop(_mk, None)
        await database.update_user_data(user_id)
        await update_user_settings(query, stype="ffset")
    elif data[2] in ["gd", "rc"]:
        await query.answer()
        du = "rc" if data[2] == "gd" else "gd"
        update_user_ldata(user_id, "DEFAULT_UPLOAD", du)
        await update_user_settings(query, stype="general")
        await database.update_user_data(user_id)
    elif data[2] in [
        "vidtools",
        "vid_merge",
        "vid_audmux",
        "vid_hardsub",
        "vid_subsync",
        "vid_compress",
        "vid_convert",
        "vid_watermark",
        "vid_extract",
        "vid_trim",
        "vid_rmstream",
    ]:
        await query.answer()
        await update_user_settings(query, data[2])
    elif data[2] == "vid_setting":
        if len(data) < 4 or data[3] not in _VID_SETTING_MAP:
            await query.answer("Unknown tool!", show_alert=True)
            return
        await query.answer()
        await update_user_settings(query, _VID_SETTING_MAP[data[3]])
    elif data[2] == "toggle_vid":
        if len(data) < 4:
            await query.answer("Missing tool key!", show_alert=True)
            return
        vid_key  = data[3]
        disabled = set(user_dict.get("disabled_vidtools", []))
        if vid_key in disabled:
            disabled.discard(vid_key)
            await query.answer(f"{vid_key} Enabled ✅", show_alert=True)
        else:
            disabled.add(vid_key)
            await query.answer(f"{vid_key} Disabled ❌", show_alert=True)
        update_user_ldata(user_id, "disabled_vidtools", list(disabled))
        await database.update_user_data(user_id)
        await update_user_settings(query, _TOGGLE_BACK_MAP.get(vid_key, "vidtools"))
    elif data[2] == "vid_cycle":
        if len(data) < 4:
            await query.answer("Missing field!", show_alert=True)
            return
        field = data[3]
        opts  = _VID_FIELD_OPTIONS.get(field, [])
        if not opts:
            await query.answer("Unknown field!", show_alert=True)
            return
        current  = user_dict.get(field, _VID_DEFAULTS.get(field, opts[0]))
        next_val = opts[(opts.index(current) + 1) % len(opts)] if current in opts else opts[0]
        update_user_ldata(user_id, field, next_val)
        await database.update_user_data(user_id)
        await query.answer(f"{field.replace('_', ' ').title()} → {next_val.title()}", show_alert=True)
        _FIELD_STYPE = {
            "vid_merge_mode":     "vid_merge",
            "vid_audio_codec":    "vid_audmux",
            "vid_convert_format": "vid_convert",
            "vid_watermark_pos":  "vid_watermark",
        }
        await update_user_settings(query, _FIELD_STYPE.get(field, "vidtools"))
    elif data[2] == "vid_set":
        if len(data) < 5:
            await query.answer("Missing args!", show_alert=True)
            return
        field, value = data[3], data[4]
        update_user_ldata(user_id, field, value)
        await database.update_user_data(user_id)
        await query.answer(f"{field.replace('_', ' ').title()} → {value.upper()}", show_alert=True)
        _FIELD_STYPE_SET = {
            "vid_264_preset":     "vid_compress",
            "vid_265_preset":     "vid_compress",
            "vid_convert_format": "vid_convert",
        }
        await update_user_settings(query, _FIELD_STYPE_SET.get(field, "vidtools"))
    elif data[2] == "vid_multi":
        if len(data) < 5:
            await query.answer("Missing args!", show_alert=True)
            return
        field, item = data[3], data[4]
        opts = _VID_MULTI_OPTIONS.get(field, [])
        if not opts or item not in opts:
            await query.answer("Unknown option!", show_alert=True)
            return
        current = list(user_dict.get(field, _VID_DEFAULTS.get(field, [])))
        if item in current:
            current.remove(item)
            await query.answer(f"{item.title()} removed ❌", show_alert=True)
        else:
            current.append(item)
            await query.answer(f"{item.title()} added ✅", show_alert=True)
        update_user_ldata(user_id, field, current)
        await database.update_user_data(user_id)
        _MULTI_STYPE = {
            "vid_extract_streams": "vid_extract",
            "vid_rmstream_kind":   "vid_rmstream",
        }
        await update_user_settings(query, _MULTI_STYPE.get(field, "vidtools"))
    elif data[2] == "rem_vid":
        if len(data) < 4:
            await query.answer("Missing field!", show_alert=True)
            return
        field = data[3]
        user_dict.pop(field, None)
        update_user_ldata(user_id, field, "")
        await database.update_user_data(user_id)
        await query.answer(f"{field.replace('_', ' ').title()} reset!", show_alert=True)
        _REM_STYPE = {
            "vid_audio_lang":        "vid_audmux",
            "vid_subsync_delay":     "vid_subsync",
            "vid_watermark_text":    "vid_watermark",
            "vid_watermark_opacity": "vid_watermark",
            "vid_trim_start":        "vid_trim",
            "vid_trim_end":          "vid_trim",
            "vid_banner":            "vid_compress",
            "vid_hardsub_font":      "vid_hardsub",
            "vid_hardsub_size":      "vid_hardsub",
        }
        await update_user_settings(query, _REM_STYPE.get(field, "vidtools"))
    elif data[2] == "vid_settext":
        if len(data) < 4 or data[3] not in _VID_INPUT_MAP:
            await query.answer("Unknown field!", show_alert=True)
            return
        await query.answer()
        field  = data[3]
        label, prompt, back_stype = _VID_INPUT_MAP[field]
        buttons_vt = ButtonMaker()
        buttons_vt.data_button("⏹ Stop", f"userset {user_id} {back_stype}")
        buttons_vt.data_button("« Back",  f"userset {user_id} {back_stype}", "footer")
        buttons_vt.data_button("✘ Close", f"userset {user_id} close",        "footer")
        await edit_message(
            message,
            f"<b>✏️ Set {label}</b>\n\n{prompt}\n\n⏱ <b>Time Left :</b> <code>60 sec</code>",
            buttons_vt.build_menu(2),
        )
        rfunc = partial(update_user_settings, query, back_stype)
        pfunc = partial(set_vid_text_option, field=field, rfunc=rfunc)
        await event_handler(client, query, pfunc, rfunc)
    elif data[2] == "back":
        await query.answer()
        stype = data[3] if len(data) == 4 else "main"
        await update_user_settings(query, stype)
    else:
        await query.answer()
        await delete_message(message, message.reply_to_message)


@new_task
async def get_users_settings(_, message):
    msg = ""
    if auth_chats:
        msg += f"AUTHORIZED_CHATS: {auth_chats}\n"
    if sudo_users:
        msg += f"SUDO_USERS: {sudo_users}\n\n"
    if user_data:
        for u, d in user_data.items():
            kmsg = f"\n<b>{u}:</b>\n"
            if vmsg := "".join(
                f"{k}: <code>{v or None}</code>\n" for k, v in d.items()
            ):
                msg += kmsg + vmsg
        if not msg:
            await send_message(message, "No users data!")
            return
        msg_ecd = msg.encode()
        if len(msg_ecd) > 4000:
            with BytesIO(msg_ecd) as ofile:
                ofile.name = "users_settings.txt"
                await send_file(message, ofile)
        else:
            await send_message(message, msg)
    else:
        await send_message(message, "No users data!")
