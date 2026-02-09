import json
import logging
from xml.sax.saxutils import escape

import aiohttp
import requests

from env import BOT_TOKEN, CHAT_ID, CMC_PRO_API_KEY, ADDRESS

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


logger = logging.getLogger(__name__)

GUIDE = """Hi!
`/stonks` = `/stonks ETH LDO`
`/stonks <token>` - show token stonks.
`/stonks <token_1> <token_2>` - show tokens stonks and relative price.
"""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends explanation on how to use the bot."""
    await update.message.reply_text(GUIDE, parse_mode='MarkdownV2')


async def show_stonk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 1:
        msg = await send_token_price(context.args[0])
        return await update.message.reply_text(escape(msg), parse_mode='MarkdownV2')

    if not context.args:
        msgs = await send_tokens_prices('ETH', 'LDO')
    else:
        msgs = await send_tokens_prices(context.args[0], context.args[1])

    await update.message.reply_text(escape('\n\n'.join(msgs)), parse_mode='MarkdownV2')


async def send_token_price(token: str):
    price, percent1h = await get_token_price(token)
    msg = token_stonks_to_msg(token, price, percent1h)
    return msg


async def send_tokens_prices(token_1: str, token_2: str) -> list[str]:
    price_1, percent1h_1 = await get_token_price(token_1)
    msg1 = token_stonks_to_msg(token_1, price_1, percent1h_1)
    price_2, percent1h_2 = await get_token_price(token_2)
    msg2 = token_stonks_to_msg(token_2, price_2, percent1h_2)
    msg3 = f'1 {token_1} \\= {price_1/price_2:.0f} {token_2}'
    return [msg1, msg2, msg3]


async def get_token_price(token: str) -> tuple[float, float]:
    url = 'https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest'

    params = {
        'convert': 'USD',
        'symbol': token,
    }
    headers = {
        'Accepts': 'application/json',
        'X-CMC_PRO_API_KEY': CMC_PRO_API_KEY,
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as response:
            try:
                data = json.loads(await response.text())
            except Exception as e:
                logger.error(e)
                return 0, 0

    logger.debug(data)

    return (
        data['data'][token]['quote']['USD']['price'],
        data['data'][token]['quote']['USD']['percent_change_1h'],
    )


def escape(msg: str) -> str:
    msg = msg.replace('.', '\\.')
    msg = msg.replace('+', '\\+')
    msg = msg.replace('-', '\\-')
    return msg


async def send_message_to_group(msg: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": escape(msg),
        "parse_mode": "MarkdownV2",
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, data=payload) as response:
                logger.debug(response)
        except Exception as e:
            logger.error(e)


def token_stonks_to_msg(token: str, price: float, percent: float) -> str:
    trend = "📈" if percent > 0 else "📉"
    trend_symb = "+" if percent > 0 else ""
    msg = f"{token} price: *{price:.2f}$*\n{token} trend: {trend_symb}{percent:.1f}% {trend} in one hour"
    return msg


async def setup_trend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.job_queue.run_once(check_trend_for_group, when=1, data=0)


async def check_trend_for_group(context: ContextTypes.DEFAULT_TYPE) -> None:
    count = context.job.data

    # TODO: dry
    token_1, token_2 = 'ETH', 'LDO'

    price_1, percent1h_1 = await get_token_price(token_1)
    msg1 = token_stonks_to_msg(token_1, price_1, percent1h_1)

    price_2, percent1h_2 = await get_token_price(token_2)
    msg2 = token_stonks_to_msg(token_2, price_2, percent1h_2)

    msg3 = f'1 {token_1} \\= {price_1/price_2:.1f} {token_2}'

    checks_in_day = 48

    if abs(percent1h_1) >= 5 or abs(percent1h_2) >=5 or count % checks_in_day == 0:
        await send_message_to_group('\n\n'.join((msg1, msg2, msg3)))

    count += 1
    context.job_queue.run_once(check_trend_for_group, when=(60 * 60 * 24) / checks_in_day, data=count)

async def check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    res = requests.get(f'https://indexer.dydx.trade/v4/addresses/{ADDRESS}').json()
    balance = res['subaccounts'][0]

    total_sur_plus = sum(int(float(position['unrealizedPnl'])) for position in balance['openPerpetualPositions'].values())

    msg = f'''Balance: ${round(float(balance['equity']), 2)}
Free collateral: ${round(float(balance['freeCollateral']), 2)}
Total sur{'plus' if total_sur_plus > 0 else 'minus'}: {'💰' * len(str(total_sur_plus)) if total_sur_plus > 0 else '😭'} ${round(float(total_sur_plus), 2)}
'''
    for position in balance['openPerpetualPositions'].values():
        msg += f'''
{position['market']}
size: {'🟢' if position['side'] == 'LONG' else '🔴'}{position['side']}-{position['size']}
entry price: ${round(float(position['entryPrice']), 2)}
unrealizedPnl: {'💰' if float(position['unrealizedPnl']) > 0 else '💔'}${round(float(position['unrealizedPnl']),2 )}
'''
    await update.message.reply_text(escape(msg), parse_mode='MarkdownV2')


def main():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler(["start", "help"], start))
    application.add_handler(CommandHandler("stonks", show_stonk))

    application.add_handler(CommandHandler("trend", setup_trend))
    application.add_handler(CommandHandler("balance", check_balance))

    application.run_polling(allowed_updates=Update.ALL_TYPES)


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    main()
