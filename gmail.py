#!/usr/bin/env python3
"""
Работа с GMail через CDP для извлечения кода подтверждения.
"""

import logging
import re
import time
from operator import itemgetter

import trio_cdp
from trio_cdp import dom, input_, open_cdp, page, target

from cdp_utils import *

logger = logging.getLogger('magicstore')


class CaptchaRequiredError(RuntimeError):
    """Для входа в Gmail требуется reCAPTCHA (ручное вмешательство)"""
    pass


async def extract_confirmation_code_from_gmail(conn, acc, url='https://gmail.com', force_new_tab=False):
    """Открыть Gmail, выполнить вход и извлечь код подтверждения из письма MagicID.

    Возвращает строку с кодом либо None, если письмо не найдено.
    """
    target_id = await find_or_create_tab(conn, 'mail.google.com')
    logger.info('Attaching to target id=%s', target_id)
    async with conn.open_session(target_id) as session:
        logger.info('Navigating to %s', url)
        await page.enable()
        async with session.listen(page.NavigatedWithinDocument) as events:
            await page.navigate(url)

            email, password = itemgetter('address', 'password')(acc['mail'])
            async for event in events:
                print(event)
                match event.url:
                    case u if u.endswith('#inbox'): break
                    case u if u.endswith('gmail/about/'):
                        root = (await dom.get_document()).node_id
                        node = await dom.query_selector(root, 'header a[data-action="sign in"]')
                        await click_node(node, type='touch')
                    case u if 'accounts.google.com/v3/signin/identifier' in u:
                        root = (await dom.get_document()).node_id
                        node = await dom.query_selector(root, 'input#email')
                        await node_insert_text(node, email, press_enter=True)
                    case u if 'signin/v2/challenge/recaptcha' in u:
                        # FIXME: another target?
                        time.sleep(1)
                        root = (await dom.get_document()).node_id
                        node = await dom.query_selector(root, 'iframe[title="reCAPTCHA"] div.recaptcha-checkbox-border')
                        await click_node(node, type='touch')

                    case u if '/signin/challenge/recaptcha' in u:
                        logger.error('GMail: reCAPTCHA required: %s %s', email, u)
                        raise CaptchaRequiredError('reCAPTCHA required')
                    case u if '/signin/v2/challenge/pwd':
                        root = (await dom.get_document()).node_id
                        node = await dom.query_selector(root, 'input#password')
                        await node_insert_text(node, password, press_enter=True)


        root, nodeFound = (await dom.get_document()).node_id, False
        for node in await dom.query_selector_all(root, 'table > tbody > tr'):
            if nodeFound := '1 Step to Make MagicID' in await dom.get_outer_html(node):
                break
        if nodeFound:
            async with session.wait_for(page.NavigatedWithinDocument):
                try: await dom.focus(node)
                except trio_cdp.BrowserError: pass
                await click_node(node, focus=False, type='touch')
        else: return None

        root = await dom.get_document()
        node = await dom.query_selector(root.node_id, 'div[data-message-id]')
        mail = re.sub(r'<.+?>', '', await dom.get_outer_html(node))
        code = re.search(r'confirmation code here:.*?(\d+)', mail).group(1)
        logger.info('Got the confirmation code: %s', code)
        logger.info('Closing target %s', target_id)
        await target.close_target(target_id)
        return code
