from bot.helper.themes import wzml_minimal


def BotTheme(var_name, **format_vars):
    text = getattr(wzml_minimal.WZMLStyle(), var_name, None)
    if text is None:
        return ""
    return text.format_map(format_vars)



