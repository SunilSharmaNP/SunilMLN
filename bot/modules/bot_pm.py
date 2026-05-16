from ..core.tg_client import TgClient


async def botpm_callback(client, query):
    """
    'View in Bot PM' button is now a URL button (t.me/BotName).
    Files are automatically sent to user PM during upload via _copy_media().
    This callback kept only so the registered handler does not crash on
    any stray '^botpm' query that might still arrive.
    """
    await query.answer(
        f"Open @{TgClient.BNAME} to view your files in Bot PM.",
        show_alert=True,
    )
