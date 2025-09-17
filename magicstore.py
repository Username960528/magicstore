"""
Действия для сайта Magic Store:
- Открытие настроек/профиля, заполнение данных, подтверждение email.
- Логин через EVM Wallet (MetaMask), голосования, Gitcoin, получение XP.
"""

import logging
import re
import time
from itertools import count, pairwise
from random import choice, choices, randint

import trio
import trio_cdp
from trio_cdp import dom, page, target

from cdp_utils import (afind, click_node,
                       dispatch_key_press, find_or_create_tab, node_attributes,
                       node_text,
                       node_insert_text, query_and_click_node, query_selector,
                       query_selector_all, query_selector_shadow)
from gmail import CaptchaRequiredError, extract_confirmation_code_from_gmail
from metamask import (MetamaskNotLoggedInError, is_metamask_url,
                      metamask_signature_request)
from utils import *

logger = logging.getLogger('magicstore')

URL = 'https://magic.store'
REFURLS = [
    'https://magic.store/ref/8Za2CXVSF5a2MPuFFkU2xk',
    'https://magic.store/ref/BdcWeLiqWeRuvtdVeeLwof',
    'https://magic.store/ref/Fqfq8DDuhy1Ufvr1MVbZoz',
    'https://magic.store/ref/L9J877gGxAnrKchz8EM7YA',
    'https://magic.store/ref/XJVjwYyKE6XdoMVAKQTZ6W',
    'https://magic.store/ref/RCvxvQ9iKbtzQ7YSqtWmnV',
    'https://magic.store/ref/7pWRnf4GzDqZmqMxb1ob72',
    'https://magic.store/ref/2rKEfhtztrpuq4ULjkReoi',
    'https://magic.store/ref/UBTRzX4sYTXGiJHWJjQKu',
    'https://magic.store/ref/2F2KtuZnAZSj19D8w5wp8u',
    'https://magic.store/ref/HnWHC24s2kB1wbq3wQh6t1',
    'https://magic.store/ref/ERFay7jnBeoUH3cWVzv5XE',
    'https://magic.store/ref/GQErqFxR63JFXW2KruBMnj',
    'https://magic.store/ref/PWNTf4fBEp7PNoB1XDvcF',
    'https://magic.store/ref/4KCkqCNh3zkqhrr7S7eTBV',
]
USE_REFS = False

async def magicstore_open_settings(conn, session):
    """Открыть страницу настроек профиля Magic Store для текущей сессии."""
    def foo(fn):
        return lambda e: (e.target_info.target_id == session.target_id
                     and fn(debug(e.target_info.url)))
    logger.info("Open settings")
    #async with session.listen(page.NavigatedWithinDocument) as events:
    async with conn.listen(target.TargetInfoChanged) as events:
        if '/magic.store' not in (await dom.get_document()).document_url:
            logger.info("Navigating to magic.store")
            await page.navigate('https://magic.store/')
            await afind(events, foo(lambda url: url == 'https://magic.store/'),
                        timeout=25, error_msg='Open magicstore page timeout')
            time.sleep(5)

        root = await dom.get_document()
        await query_and_click_node(root, 'button img[data-qa="account-avatar"]',
                                   focus=False, name='Account', try_hard=5, delay=2)
        await query_and_click_node(root, 'div.menu-list > button',
                                   name="Settings", type='touch')
        await afind(events, foo(lambda x: x.endswith('/profile/settings')),
                    timeout=30, error_msg='Settings page timeout')


async def magicstore_fill_profile(conn, target_id, acc):
    """Заполнить профиль: логин, отображаемое имя, email и подтвердить код с почты.

    acc — словарь аккаунта с полем `mail` (address, password).
    """
    async def confirm_input(node):
        await dom.focus(node)
        await dispatch_key_press('Enter', text='\r', unmodified_text='\r')

    async def input_fuckery(query, value):
        async with session.listen(dom.AttributeModified) as events:
            node = await dom.query_selector(root.node_id, query)
            match (await node_attributes(node)).get('value', ''):
                case '':  # FIXME if not disabled
                    await node_insert_text(node, value)
                    async for event in events:
                        if event.name == 'class' and 'collapsible-open' in event.value:
                            return node, event, value
                case x:
                    return node, None, x

    while(True):
        username = MARKOV.generate(min_length=8, max_length=16)
        # FIXME: слишком однообразные и палевные
        #username = generate_username(WORDS)
        login    = username #+ str(randint(1000, 9999))
        if len(login) <= 20: break
    try:
        email = acc['mail']['address']
    except KeyError:
        return

    if acc.get('magicstore', {}).get('email_confirmed', False):
        return

    logger.info('Gonna try to fill profile')
    time.sleep(5)

    logger.info('Attaching to target id=%s', target_id)
    async with conn.open_session(target_id) as session:
        await page.enable()
        root = await dom.get_document()
        # Check if profile is already filled
        # if await is_profile_filled(root):
        #     logger.info('Profile already filled, proceeding to vote.')
        #     await magicstore_vote_page(conn, session, acc)  # Proceed to voting
        #     return
        if '/profile/settings' not in root.document_url:
            await magicstore_open_settings(conn, session)
            time.sleep(5)
            root = await dom.get_document()
            logger.info("Url: %s", root.document_url)
            await query_and_click_node(root, 'button[data-qa="profile-add-button"]',
                                       try_hard=5, delay=4, name='Edit profile')
            time.sleep(3)

        # Permanent username
        node, event, login = await input_fuckery('input#username', login)
        if event:
            if '<button' not in await dom.get_outer_html(event.node_id):
                # FIXME: try again
                #return magicstore_fill_profile()
                raise RuntimeError('Okaaaay')
            await confirm_input(node)
        # Displayed name
        node, event, username = await input_fuckery('input#displayedName', username)
        if event: await confirm_input(node)
        # EMail
        node, event, email = await input_fuckery('input#email', email)
        if event:
            await confirm_input(node)
            # EMail confirmation code
            time.sleep(10)
            code = await extract_confirmation_code_from_gmail(conn, acc)
            if not code:
                raise RuntimeError('Could not extract confirmation code')
            node = await dom.query_selector(root.node_id, 'article#profile-email-field > div.collapsible-open input')
            await node_insert_text(node, code, press_enter=True)
            time.sleep(10)
        acc |= {'magicstore': {'login': login,
                               'username': username,
                               'email_confirmed': True}}
        update_account(acc)


async def magicstore_login(conn, acc, target_id=None, force_new_tab=False):
    """Логин на Magic Store. Возвращает target_id вкладки.

    При необходимости открывает реферальную страницу, инициирует MetaMask подпись.
    """
    if not target_id:
        target_id = await find_or_create_tab(conn, URL, force_new_tab=force_new_tab)
    await target.activate_target(target_id)
    logger.info('Attaching to target id=%s', target_id)
    async with conn.open_session(target_id) as session:
        await page.enable()
        root = await dom.get_document()
        async with session.listen(page.NavigatedWithinDocument) as events:
            # await page.navigate(URL)
            # await afind(events, lambda e: 'https://magic.store/' == e.url,
            #             each=print, timeout=20)
            if USE_REFS and not acc.get('magicstore', False):
                url = choice(REFURLS)
                logger.info('Using refurl %s', url)
                await page.navigate(url)
                if not await afind(events, lambda e: e.url.endswith('/coinlist-magicsquare-road-to-tge-quests'),
                                   timeout=30, noerror=True):
                    await page.navigate(URL)
            elif '//magic.store' not in root.document_url:
                logger.info('Navigating to %s', URL)
                await page.navigate(URL)
                await afind(events, lambda e: 'https://magic.store/' == e.url, timeout=20)

        async with session.listen(dom.AttributeModified) as attrs_modified:
            root = await dom.get_document()
            nodes = await query_selector_all(root, 'aside > nav button', try_hard=5, delay=10)
            print(nodes)
            [node] = [x for x in nodes if ">Account<" in await dom.get_outer_html(x)]
            await click_node(node, type='touch', name='Account')
            await afind(attrs_modified, lambda _: True, timeout=30, noerror=True)

        nodes = await dom.query_selector_all(root.node_id, 'div[role="dialog"] button')
        nodes = (x for x in nodes if 'EVM Wallet' in await dom.get_outer_html(x))
        if not (node := await anext(nodes, None)):
            return target_id
        async with conn.listen(target.TargetInfoChanged) as events:
            await click_node(node, type='touch', name='Login with EVM Wallet')
            e = await afind(events, lambda e: is_metamask_url(e.target_info.url),
                            timeout=90, error_msg='Login timeout')
            mmtid = e.target_info.target_id

    #async with session.wait_for(page.FrameStoppedLoading):
    await metamask_signature_request(conn, mmtid, acc)
    time.sleep(15) # FIXME
    return target_id


async def magicstore_open_voting_page(conn, session):
    """Перейти на страницу заданий для валидации (голосования)."""
    await page.enable()
    await magicstore_open_settings(conn, session)
    async with session.listen(page.NavigatedWithinDocument) as events:
        time.sleep(0.1)
        root = await dom.get_document()
        await query_and_click_node(root, 'a[href="/profile/validation-tasks"]',
                                   name='Validations Tasks',
                                   try_hard=5, type='touch')
        await afind(events, lambda x: x.url.endswith('/profile/validation-tasks'), each=print,
                    timeout=15, error_msg="Validation tasks page timeout")


async def magicstore_vote_page(conn, session, acc):
    """Проголосовать по всем доступным пунктам на текущей странице.

    Возвращает количество совершённых голосов.
    """
    root, voted_at_least_once = (await dom.get_document()).node_id, 0
    for vote in await query_selector_all(root, 'div.profile-container li > article',
                                         try_hard=5, errorp=False):
        logger.info("Voting node %s", vote)
        node = await dom.query_selector(vote, 'div.collapsible-open a[data-qa="vote-button"]')
        if node == 0:
            while True:
                async with session.listen(dom.AttributeModified) as events:
                    try:
                        await query_and_click_node(vote, 'section button', type='touch')
                    except RuntimeError: pass
                    except trio_cdp.BrowserError: pass
                    try:
                        await afind(events, lambda e: e.name == 'class' and 'collapsible-open' in e.value,
                                    each=print, timeout=5)
                    except TimeoutError: pass
                    else: break
        #FIXME обернуть всю голосовалку
        with trio.move_on_after(30) as scope:
            time.sleep(2)
            node = await query_selector(vote, 'div.collapsible-open a[data-qa="vote-button"]')
            if 'Voted' in await dom.get_outer_html(node):
                return voted_at_least_once
            async with session.wait_for(dom.ChildNodeItonserted):
                await click_node(node, type='touch', name='Vote')
        if scope.cancelled_caught:
            raise TimeoutError("Vote button")

        while True:
            try:
                [_, visit] = await dom.query_selector_all(root, 'div[role="dialog"] a')
                node_attrs = await node_attributes(visit)
                visit_url = re.search(r'^(.+?://)?([^/]+)', node_attrs['href'])[2]
                logger.info('Voting for %s', visit_url)
                break
            except ValueError: pass

        #FIXME
        with trio.move_on_after(15) as scope:
            async with conn.wait_for(target.TargetCreated) as e:
                await click_node(visit, type='enter', name='Visit project page')
        if scope.cancelled_caught:
            raise TimeoutError('')
        async with conn.listen(target.TargetInfoChanged) as events:
            time.sleep(10)
            await target.close_target(e.value.target_info.target_id)

            # 75% Yes, 25% No
            yesno = await query_selector_all(root, 'div[role="dialog"] input[type="radio"]',
                                             try_hard=3, delay=1)
            await click_node(choices(yesno, [75, 25])[0], name='Yes/No radio')
            await query_and_click_node(root, 'div[role="dialog"] button.button-solid-primary',
                                       name='Next')
            tries_left = 3
            while True:
                with trio.move_on_after(60) as scope:
                    await query_and_click_node(root, 'div[role="dialog"] button.button-solid-primary',
                                               name='Confirm')
                    if e := await afind(events, lambda e: is_metamask_url(e.target_info.url),
                                        timeout=60, error_msg='Metamask popup timeout'):
                        await metamask_signature_request(conn, e.target_info.target_id, acc)
                        time.sleep(1)
                if scope.cancelled_caught:
                    if (tries_left := tries_left - 1) <= 0:
                        raise TimeoutError("")
                else:
                    break
        # Close
        async with session.wait_for(dom.ChildNodeRemoved):
            await query_and_click_node(root, 'div[role="dialog"] button.button-solid-primary',
                                       focus=False, name='Collapse')
            time.sleep(0.2)
            await query_and_click_node(vote, 'section button', type='touch', name='Close task')
            time.sleep(3)
        voted_at_least_once += 1
    return voted_at_least_once


async def magicstore_vote(conn, acc, target_id=None):
    """Обход страниц голосования до исчерпания доступных заданий."""
    logger.info('Gonna vote for all that shit')
    target_id = target_id or await find_or_create_tab(conn, 'magic.store')
    logger.info('Attaching to target %s', target_id)
    async with conn.open_session(target_id) as session:
        total, bNext = 0, None
        for nPage in count(start=1):
            if bNext:
                async with session.wait_for(page.NavigatedWithinDocument):
                    await click_node(bNext, type='touch', name='Next page')
                    time.sleep(1)
                    try:
                        await click_node(bNext, type='enter', name='Next page')
                        time.sleep(1)
                        await click_node(bNext, type='enter', name='Next page',
                                         send_text=True)
                    except trio_cdp.BrowserError: pass
            else:
                await magicstore_open_voting_page(conn, session)
            time.sleep(4)
            logger.info('Voting page #%d', nPage)
            time.sleep(2.5)
            total += (nVotes := await magicstore_vote_page(conn, session, acc))
            time.sleep(5)
            if nVotes == 0:
                if bNext:
                    bNext = 0
                    continue
                logger.info('Voting DONE: %d %s', total, acc['serial_number'])
                break
            else:
                time.sleep(5)
                root  = await dom.get_document()
                #bNext = await query_selector(root, 'button[aria-label="Go to next page"]:enabled')
                bNext, xs = 0, await query_selector_all(root, 'li > button:enabled')
                for x, y in pairwise(xs):
                    attrs = await node_attributes(x)
                    if attrs.get('aria-current', '') == 'page':
                        bNext = y
                        break


async def magicstore_gitcoin_verify(conn, acc, target_id=None):
    """Проверить и сохранить Gitcoin Passport score на странице настроек."""
    logger.info('Magicstore gitcoin verification')
    target_id = target_id or await find_or_create_tab(conn, 'magic.store')
    logger.info('Attaching to target %s', target_id)
    async with conn.open_session(target_id) as session:
        root = await dom.get_document()
        if not root.document_url.endswith('/profile/settings'):
            await magicstore_open_settings(conn, session)
        time.sleep(1)

        async with session.listen(dom.ChildNodeInserted) as events:
            await query_and_click_node('//button[normalize-space()="Verify"]',
                                       name='Verify', mode='xpath', try_hard=5, delay=2)
            div_inserted = await afind(events, lambda x: (
                x.node.node_name == 'DIV'
                and 'data-floating-ui-portal' in x.node.attributes
            ), timeout=10, noerror=True)

        time.sleep(2)
        if div_inserted:
            if await query_selector('div[data-floating-ui-portal] a[href="https://passport.gitcoin.co/"]',
                                    errorp=False):
                time.sleep(1)
                await query_and_click_node('button[data-qa="modal-close-button"]')
                #return False
            else:
                await query_and_click_node('div[data-floating-ui-portal] button.button-solid-secondary')

        time.sleep(10)
        score = await query_selector('//section[@id="profile-gitcoin-verification"]/div',
                                     mode='xpath')
        score = re.findall(r'\d+', await node_text(score))[0]
        logger.info('Gitcoin score: %s %s', acc['serial_number'], score)

        acc |= {'gitcoin': {'score': int(score)}}
        update_account(acc)
        print(f'Score: {score}')


async def magicstore_get_xp(conn, acc, target_id=None):
    """Получить XP и позицию из страницы кампании и обновить состояние аккаунта."""
    logger.info("Magicstore XP extraction")
    target_id = target_id or await find_or_create_tab(conn, 'magic.store')
    logger.info('Attaching to target %s', target_id)
    async with conn.open_session(target_id) as session:
        await page.enable()
        async with session.wait_for(page.FrameStoppedLoading):
            await page.navigate('https://magic.store/stories/coinlist-magicsquare-road-to-tge-quests')
        rows = await query_selector_all('div.grid-table-row > div.grid-table-cell', try_hard=3, delay=3)
        [pos, _, xp, sqr] = [await node_text(x) for x in rows[-4:]]
        logger.info('Account %s points: %s, %s, %s', acc['serial_number'], pos, xp, sqr)
        acc['magicstore'] |= {'position': pos, 'xp': xp, 'sqr': sqr}
        update_account(acc)
