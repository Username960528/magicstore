#!/usr/bin/env python3
"""
Обработка окон/попапов MetaMask через CDP:
- Разблокировка, импорт/восстановление, подтверждение/подпись запросов.
"""

import logging
import time
from functools import partial
from operator import itemgetter

import trio_util
from trio_cdp import dom, page, target

from cdp_utils import (afind, click_node, dispatch_key_press, node_insert_text,
                       query_selector_all, query_selector, query_and_click_node)
from utils import update_account

logger = logging.getLogger('metamask')


class MetamaskNotLoggedInError (RuntimeError):
    """MetaMask не авторизован/не сконфигурирован для данного профиля."""
    pass


async def metamask_signature_request_(connection, target_id, profile_info):
    """Обработать окно MetaMask: разблокировать/подтвердить/подписать.

    Возвращает True при успешной подписи.
    """
    logger.info('Attaching to target id=%s', target_id)
    async with connection.open_session(target_id) as session:
        await page.enable()
        logger.info("MetaMask signature request")

        try:
            is_logged_in, (wid, pwd) = True, itemgetter('id', 'password')(profile_info['wallet'])
        except KeyError:
            logger.info("MetaMask seems not logged in")
            raise MetamaskNotLoggedInError(profile_info)
            wallet = {}
            #pwd = generate_password() # '12345678'
            #is_logged_in, (wid, wallet) = False, find_unused_wallet()
            #update_account(profile_info | {'wallet': {'id': wid}})

        async with session.listen(page.NavigatedWithinDocument) as events:
            root = await dom.get_document()
            we_are_done, url = False, root.document_url
            while not we_are_done:
                logger.info("handling %s", url)
                if url.endswith('#unlock'):
                    if is_logged_in:
                        await node_insert_text(None, pwd, press_enter=True)
                    else:
                        await query_and_click_node('div.unlock-page__links > a')
                elif url.endswith('/signature-request') or '#connect/' in url:
                    [_, btn] = await query_selector_all('footer > button')
                    await click_node(btn)
                    if url.endswith('/signature-request'):
                        return True
                elif url.endswith('#confirm-transaction'):
                    pass # break
                elif any(map(url.endswith, ['#restore-vault',
                                            '#onboarding/import-with-recovery-phrase'])):
                    # Восстановление/импорт кошелька из seed-фразы
                    nodes = await query_selector_all('div.import-srp__srp-word input[type="password"]')
                    for node, word in zip(nodes, wallet['words']):
                        await node_insert_text(node, word)
                    if url.endswith('#restore-vault'):
                        for node in await query_selector_all('input[autocomplete="new-password"]'):
                            await node_insert_text(node, pwd)
                        await dispatch_key_press('Enter', text='\r')
                        # FIXME not checking, I'm lucky... and blind btw
                        pass
                        update_account(profile_info | {'wallet': {'id': wid, 'password': pwd}})
                    else:
                        query_and_click_node('button[data-testid="import-srp-confirm"]')
                elif url.endswith('#onboarding/create-password'):
                    for node in await query_selector_all('input[type="password"]'):
                        await node_insert_text(node, pwd)
                    node = await query_selector('button[data-testid="create-password-import"]')
                    await click_node(node)
                    update_account(profile_info | {'wallet': {'id': wid, 'password': pwd}})
                    we_are_done = True
                    await target.close_target(target_id)  # TODO: test
                elif url.endswith('#onboarding/welcome'):
                    print('Welcome!' + target_id)
                    time.sleep(0.5)
                    [bcreate, bimport] = await query_selector_all('ul.onboarding-welcome__buttons button')
                    await click_node(bimport)
                else: pass
                url = (await anext(events)).url


async def metamask_signature_request(conn, target_id, acc):
    """Дождаться завершения попапа MetaMask либо заново перехватить окно.

    Обработка гонок при автозакрытии и повторном открытии попапа.
    """
    async def wait_tab_closed(events):
        nonlocal popup_is_closed
        async for event in events:
            if event.target_id == target_id:
                return (popup_is_closed := True)
    popup_is_closed = False
    async with conn.listen(target.TargetCreated) as created_events:
        async with conn.listen(target.TargetDestroyed) as destroyed_events:
            await trio_util.wait_any(partial(metamask_signature_request_, conn, target_id, acc),
                                     partial(wait_tab_closed, destroyed_events))
        if popup_is_closed:
            e = await afind(created_events, lambda e: is_metamask_url(e.target_info.url))
            await metamask_signature_request_(conn, e.target_info.target_id, acc)


def is_metamask_url(url):
    """Проверить, что URL принадлежит расширению MetaMask (ID в профиле)."""
    return url.startswith('chrome-extension://jfmngdpfgiljdfoaojnioanneidgipjm/')
