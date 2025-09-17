"""
Сценарии автоматизации Magic Store и Zealy:
- Логин/линк кошелька, выполнение квестов, голосования, получение метрик.
Используется Trio + CDP; браузерный профиль запускается через AdsPower.
"""
import json
import logging
import os
import re
import sys
import time
import traceback
from portalocker import LOCK_SH, unlock, lock
from itertools import count, pairwise
from random import choice,choices, randint

import trio
import trio_cdp
from trio_cdp import dom, open_cdp, page, target

import utils
from cdp_utils import (QuerySelectorError, afind, click_node,
                       dispatch_key_press, find_or_create_tab, node_attributes,
                       node_insert_text, query_and_click_node, query_selector,
                       query_selector_all, query_selector_shadow)
from gmail import CaptchaRequiredError, extract_confirmation_code_from_gmail
from metamask import (MetamaskNotLoggedInError, is_metamask_url,
                      metamask_signature_request)
from magicstore import (magicstore_open_settings, magicstore_fill_profile,
                        magicstore_vote, magicstore_login, magicstore_gitcoin_verify)
from utils import *


async def zealy_login(session):
    """Войти в Zealy (через Discord OAuth при необходимости)."""
    logger.info("Zealy login")
    async with session.wait_for(page.FrameStoppedLoading):
        await page.navigate('https://zealy.io/login')
    time.sleep(5)

    root = await dom.get_document()
    if 'zealy.io/login' not in root.document_url:
        logger.info('Zealy seems logged in')
        return

    found, buttons = False, await query_selector_all(root, 'main section button')
    for btn in buttons:
        if 'Log in with Discord' in await dom.get_outer_html(btn):
            found = True
            break

    if not found: raise RuntimeError('xz')
    with session.listen(page.NavigatedWithinDocument) as events:
        async with session.wait_for(page.FrameStoppedLoading):
            await click_node(btn, type='touch', focus=False,
                             name='Log in with Discord')
        time.sleep(5)
        #await afind(events, lambda x: 'discord.com/oauth2/authorize' in x.url,
        #            timeout=30)

        # FIXME: да-да, лапша. Стоит выделить в отдельные функции
        root = await dom.get_document()
        buttons, found = await query_selector_all(root, 'button', try_hard=5, delay=5), False
        for btn in buttons:
            if 'Authorize' in await dom.get_outer_html(btn):
                found = True
                break
        if not found: raise RuntimeError('zz')

        await click_node(btn, focus=False, type='touch', name='Authorize')
        await afind(events, lambda x: '//zealy.io' in x.url, timeout=30)


async def zealy_link_wallet(conn, session, acc):
    """Привязать кошелёк к Zealy через Web3Modal и MetaMask."""
    root = await dom.get_document()
    for node in await dom.query_selector_all(root.node_id, 'div.rounded-component-md'):
        print(node)
        if 'Connect your Wallet' in await dom.get_outer_html(node):
            btn = await dom.query_selector(node, 'button')
            if 'Connect' in await dom.get_outer_html(btn):
                await click_node(btn, name='Connect Wallet')
                time.sleep(1)
                async with conn.listen(target.TargetInfoChanged) as targets:
                    btn = await query_selector_shadow(root, [
                        'w3m-modal',
                        'w3m-router',
                        'w3m-connect-view',
                        'wui-list-wallet[name="Browser Wallet"]',
                        'button'], try_hard=3)
                    await click_node(btn, focus=False)
                    tinf = await afind(targets, lambda e: is_metamask_url(e.target_info.url))
                async with session.listen(dom.ChildNodeInserted) as events:
                    await metamask_signature_request(conn, tinf.target_info.target_id, acc)
                    await afind(events, lambda e: e.node.node_name == 'BUTTON'
                                and [n for n in e.node.children if n.node_value == 'Disconnect'],
                                each=print)
                #time.sleep(30)
                #FIXME: ожидать появления кнопки disconnect
            break
    acc |= {'zealy': {'wallet_linked': True}}
    update_account(acc)


async def zealy_verification(conn, acc, target_id=None):
    """Выполнить начальные задания/верификации Zealy и отметить прогресс."""
    if acc.get('zealy', {}).get('first_tasks_completed', False):
        return

    target_id = target_id or await find_or_create_tab(conn, 'zealy.io')
    async with conn.open_session(target_id) as session:
        await page.enable()
        if not acc.get('zealy', {}).get('wallet_linked', False):
            await zealy_login(session)
            time.sleep(5)
            async with session.wait_for(page.FrameStoppedLoading):
                await page.navigate('https://zealy.io/cw/_/settings/linked-accounts')
            time.sleep(10)
            await zealy_link_wallet(conn, session, acc)

        while True:
            async with session.wait_for(page.FrameStoppedLoading):
                await page.navigate('https://zealy.io/c/magicsquareroadtotge')
            root = await dom.get_document()
            task = await query_selector(root, 'div[id][open]', try_hard=10, delay=3)
            match tid := (await node_attributes(task))['id']:
                case '3d3edccb-91f4-49ef-b733-e365b59b51b1':
                    async with session.wait_for(page.FrameStoppedLoading):
                        await click_node(task, focus=False, name=f'Task {tid}')
                    async with session.wait_for(page.FrameStoppedLoading):
                        await query_and_click_node(root, 'div.css-0 > div.chakra-stack > div',
                                                   focus=False, try_hard=True)
                        await query_and_click_node(root, 'section[role="dialog"] button.chakra-button',
                                                   try_hard=True, name='Claim Reward')
                        time.sleep(1)
                case '01f71881-6b6a-43a2-801e-042353a034b5':
                    async with session.wait_for(page.FrameStoppedLoading):
                        await click_node(task, focus=False, name=f'Task {tid}')
                    time.sleep(2)
                    [visit, reward] = await dom.query_selector_all(root.node_id, 'section.chakra-modal__content button')
                    async with conn.listen(target.TargetInfoChanged) as events:
                        await click_node(visit)
                        e = await afind(events, lambda e:
                                        e.target_info.url.endswith('coinlist-magicsquare-road-to-tge-quests'))
                    await magicstore_login(conn, acc, target_id=e.target_info.target_id)
                    async with conn.open_session(e.target_info.target_id) as mstore:
                        try:
                            async with mstore.wait_for(dom.AttributeModified):
                                root = await dom.get_document()
                                await query_and_click_node(root, 'div.collapsible-open button',
                                                           try_hard=5)
                        except QuerySelectorError: pass
                    time.sleep(10)
                    await target.close_target(e.target_info.target_id)
                    await click_node(reward, name='Claim Reward')
                    time.sleep(1)
                case _:
                    break
        acc['zealy'] |= {'first_tasks_completed': True}
        update_account(acc)


async def zealy_solver(conn, session, acc, task, tid):
    """Решить конкретное задание Zealy по идентификатору tid.

    Возвращает (успешно: bool, пропущено: bool).
    """
    async def open_task():
        while True:
            try:
                async with session.listen(page.FrameStoppedLoading) as events:
                    await dom.scroll_into_view_if_needed(task)
                    await click_node(task, focus=False, name=f'Task {tid}')
                    await afind(events, lambda _: True, timeout=10)
                    break
            except TimeoutError:
                pass

    async def confirm_and_claim_reward(text):
        await open_task()
        async with session.wait_for(page.FrameStoppedLoading):
            await query_and_click_node(
                f'//section[@role="dialog"] //div[contains(@class, "chakra-stack")] //p[contains(text(),"{text}")]',
                mode='xpath', focus=False, try_hard=10, name=f'"{text}"')
            await query_and_click_node('section[role="dialog"] button.chakra-button',
                                       try_hard=10, name='Claim Reward')
            time.sleep(1)

    def tinfo_url(fn):
        return lambda event: fn(event.target_info.url)

    async def visit_page_and_claim_reward(pred=lambda _: True, doshit=None, delay=20):
        await open_task()
        time.sleep(2)
        [visit, reward] = await query_selector_all('section.chakra-modal__content button')
        async with conn.listen(target.TargetCreated) as events:
            await click_node(visit)
            e = await afind(events, pred)
        doshit and await doshit()
        time.sleep(delay)
        await target.close_target(e.target_info.target_id)
        await click_node(reward, name='Claim Reward')
        time.sleep(1)

    async def twitter_like_repost(button='Retweet'):
        await open_task()
        time.sleep(10)
        async with conn.listen(target.TargetCreated) as events:
            await query_and_click_node(f'//section[@role="dialog"] //button[text()="{button}"]',
                                       mode='xpath')
            event = await afind(events, lambda x: x.target_info.type_ == 'page')
        time.sleep(5)
        await target.close_target(event.target_info.target_id)
        #await query_and_click_node('//div[@role="button"] // span[text()="Share"]',
        #                           mode='xpath', try_hard=5, delay=3, type='touch')
        #await query_and_click_node('//a[starts-with(@aria-label, "Like")]',
        #                           mode='xpath')
        await query_and_click_node('//section[@role="dialog"] //button[text()="Claim Reward"]',
                                   mode='xpath', try_hard=10, name='Claim Reward')
        time.sleep(5)

    logger.info("Solving %s zealy quest", tid)
    success, skipping = True, False
    match tid:

        case ('055672aa-909a-4000-8cfa-797dc5f575c0':
            await confirm_and_claim_reward('I confirm') #
        case '106410e4-4f91-460c-8c05-62e7e1378b1d':
            await confirm_and_claim_reward('I Confirm')
        case '131881eb-8aec-4400-b876-0525f45970d0': #
            await confirm_and_claim_reward('I understand')
        case '9dfdeaf6-c120-44ef-820d-2f80dd9d957b':
            await confirm_and_claim_reward('$SQR')
        case '26b40630-0771-4b7a-a8d1-6531f192c4dc':
            await confirm_and_claim_reward('10,000 $SQR')
        case '4da5cb63-9d27-4e14-b4fd-341e55ccfbce':
            await confirm_and_claim_reward('No lockup, no vesting')
        case '05de7024-2a1e-4caa-8aec-8c5350cb115a':
            await confirm_and_claim_reward('18')
        case 'b2d275cd-3d81-4a3d-a7b8-2bce115deabe':
            await confirm_and_claim_reward('Exclusive Magic Store Opportunities')
        case ('4e5755eb-867b-461e-aa7d-51f20ad7ef77' | #
              'a06141c9-7439-4d2b-a9a9-6429942626cb' |
              '3e77c561-9f88-4bc3-8e9e-4214eeee014b'):
            await visit_page_and_claim_reward()
        case 'e1793d65-6852-440f-a876-ed3d6bdc0daf':
            if acc.get('gitcoin', False):
                await visit_page_and_claim_reward()
            else:
                logger.info('You should link gitcoin passport first')
                success = False
        case ('0d36d4c9-53a7-4754-82a5-ec5e4c77efe9' | #
              'e374a57a-7354-488a-98e7-4f8f96845564' |
              '934ab7e0-5783-4eff-8ea6-4a8d788dd7c3' |
              '910d9370-1eed-4b4b-8f02-2ae2e6822832' |
              'ac33a976-7a43-4828-8bd1-54865d961ef0' |
              'f5282653-603f-4656-82ba-c43195500b93'):
            await twitter_like_repost()
        case ('4c5ec819-07ab-4618-8e7d-b5810b1e4979' |
              '86e5185e-5835-4eaa-9989-216a24a67760' |
              '910d9370-1eed-4b4b-8f02-2ae2e6822832' |
              '934ab7e0-5783-4eff-8ea6-4a8d788dd7c3' |
              '934ab7e0-5783-4eff-8ea6-4a8d788dd7c3' |
              'ac33a976-7a43-4828-8bd1-54865d961ef0' |
              '2e9a12dc-f132-4ab2-bec0-2291e3675246'):
            await twitter_like_repost('Follow')
        case ('ab0499ab-78fd-4f03-868d-4e3cba2a9fb5' | # Email
              # Daily
              '07552eff-6b59-41b7-863e-ab9a8d1c269f' |
              'c870e0e5-da74-4e9a-972a-74f0c2bda03a' |
              'd7d83b05-8987-4881-8bd3-e028a2dc40a6' |
              # Tweet
              '36fe1820-221c-4d1e-ae0e-b23aa115c242' |
              # Screenshot
              '20e55b99-473b-40e1-a7ac-151f826645a4' |
              'ddb5505f-ee52-4d84-aacc-9c617bc15ee0' |
              'fbb260bb-948a-4d22-858e-17e375b82b53'):
            logger.info("Skip task %s", tid)
            skipping = True
        case _:
            logger.info("There's no solver for %s task", tid)
            success = False

    return success, skipping


async def zealy_quests(conn, acc, target_id=None):
    """Итерироваться по заданиям Zealy и решать их по одному до исчерпания."""
    if acc.get('zealy', {}).get('done', False):
        return

    target_id = target_id or await find_or_create_tab(conn, 'zealy.io')
    async with conn.open_session(target_id) as session:
        await page.enable()
        await zealy_login(session)
        time.sleep(5)

        async with session.wait_for(page.FrameStoppedLoading):
            await page.navigate('https://zealy.io/c/magicsquareroadtotge')

        success = True
        while True:
            at_least_once = False
            for task in await query_selector_all('div[id][open]', try_hard=10, delay=3):
                tid = (await node_attributes(task))['id']
                if await query_selector(task, 'svg', errorp=False):
                    logger.info("Task %s seems locked", tid)
                    continue
                solved, skipped = await zealy_solver(conn, session, acc, task, tid)
                if not skipped:
                    at_least_once |= True
                    time.sleep(3)
                    break
                success &= solved
            if not at_least_once:
                if success:
                    logger.info("Zealy DONE %s", acc['serial_number'])
                break

        async def magic_campaign(button='Retweet'):
            await open_task()
            time.sleep(10)
            async with conn.listen(target.TargetCreated) as events:
                await query_and_click_node(f'//section[@role="dialog"] //button[text()="{button}"]',
                                           mode='xpath')
                event = await afind(events, lambda x: x.target_info.type_ == 'page')
            time.sleep(5)
            await target.close_target(event.target_info.target_id)
            # await query_and_click_node('//div[@role="button"] // span[text()="Share"]',
            #                           mode='xpath', try_hard=5, delay=3, type='touch')
            # await query_and_click_node('//a[starts-with(@aria-label, "Like")]',
            #                           mode='xpath')
            await query_and_click_node('//section[@role="dialog"] //button[text()="Claim Reward"]',
                                       mode='xpath', try_hard=10, name='Claim Reward')
            time.sleep(5)

        logger.info("Solving %s zealily quest", tid)
        success, skipping = True, False
        match tid:
            case '4e5755eb-867b-461e-aa7d-51f20ad7ef77':
                await visit_page_and_claim_reward()
            # Add additional cases here as needed


        return success, skipping

async def is_profile_filled(root):
    selectors = [
        "p[class='t-subtitle3 truncate']",  # login
        "p[class='t-body4 truncate']",      # name
        ".t-body4.truncate.leading-7"       # email
    ]
    for selector in selectors:
        if await dom.query_selector(root.node_id, selector) == 0:
            return False
    return True


async def worker__voting(sID):
    """Воркер: логин, заполнение профиля, Zealy верификация и голосование."""
    acc = utils.ACCOUNTS['account'][sID]
    logger.info('Starting %s browser profile', acc['serial_number'])
    cdp_uri = ads_request('/api/v1/browser/start',
                          user_id=acc['user_id'])['ws']['puppeteer']
    time.sleep(10)
    try:
        logger.info('Connecting to browser: %s', cdp_uri)
        async with open_cdp(cdp_uri) as conn:
            for x in await target.get_targets():
                if (x.type_ == 'page'
                    and '127.0.0.1' not in x.url
                    and 'start.adspower.net' not in x.url):
                    await target.close_target(x.target_id)
            time.sleep(5)
            await target.set_discover_targets(True)
            for _ in range(10):
                acc = utils.ACCOUNTS['account'][sID]
                try:
                    tid = await magicstore_login(conn, acc)
                    await magicstore_fill_profile(conn, tid, acc)
                    await zealy_verification(conn, acc)
                    await magicstore_vote(conn, acc)
                    break
                #except QuerySelectorError: pass
                except ValueError as e:
                    traceback.print_exception(e)
                    pass
                except trio_cdp.BrowserError as e:
                    traceback.print_exception(e)
                    pass
                except TimeoutError as e:
                    traceback.print_exception(e)
                    pass
                except CaptchaRequiredError: break
                except MetamaskNotLoggedInError: break
                except RuntimeError as e:
                    traceback.print_exception(e)
                    pass
    finally:
        ads_request('/api/v1/browser/stop', user_id=acc['user_id'])


async def worker(sID):
    """Воркер: логин на Magic Store, Gitcoin проверка, выполнение квестов Zealy."""
    acc = utils.ACCOUNTS['account'][sID]
    logger.info('Starting %s browser profile', acc['serial_number'])
    cdp_uri = ads_request('/api/v1/browser/start',
                          user_id=acc['user_id'])['ws']['puppeteer']
    time.sleep(10)
    try:
        logger.info('Connecting to browser: %s', cdp_uri)
        async with open_cdp(cdp_uri) as conn:
            for x in await target.get_targets():
                if (x.type_ == 'page'
                    and '127.0.0.1' not in x.url
                    and 'start.adspower.net' not in x.url):
                    await target.close_target(x.target_id)
            time.sleep(5)
            await target.set_discover_targets(True)
            skip_magicstore = False
            for i in range(16):
                acc = utils.ACCOUNTS['account'][sID]
                try:
                    if not skip_magicstore and i <= 8:
                        tid = await magicstore_login(conn, acc)
                        await magicstore_gitcoin_verify(conn, acc, target_id=tid)
                        skip_magicstore = True
                    await zealy_quests(conn, acc)
                    break
                #except QuerySelectorError: pass
                except IndexError as e:
                    traceback.print_exception(e)
                    pass
                except ValueError as e:
                    traceback.print_exception(e)
                    pass
                except trio_cdp.BrowserError as e:
                    traceback.print_exception(e)
                    pass
                except TimeoutError as e:
                    traceback.print_exception(e)
                    pass
                except CaptchaRequiredError: break
                except MetamaskNotLoggedInError: break
                except RuntimeError as e:
                    traceback.print_exception(e)
                    pass
    finally:
        pass
        ads_request('/api/v1/browser/stop', user_id=acc['user_id'])


if __name__ == '__main__':
    sID = sys.argv[1]
    log_level = os.environ.get('LOG_LEVEL', 'info').upper()
    logging.basicConfig(level=getattr(logging, log_level),
                        format=f'%(levelname)s:%(asctime)s:%(name)s:{sID}:%(message)s')
    logger = logging.getLogger(f'magicstore')
    logging.getLogger('trio-websocket').setLevel(logging.WARNING)

    WORDS = load_dictionary('basic.json')
    MARKOV = MarkovGenerator()

    for w in WORDS['nouns']:
        MARKOV.add_seq(w)

    with open('alltheshit.json') as ifile:
        lock(ifile, LOCK_SH)
        try: utils.ACCOUNTS = json.load(ifile)
        finally:
            unlock(ifile)
    trio.run(worker, sys.argv[1], restrict_keyboard_interrupt_to_checkpoints=True)
