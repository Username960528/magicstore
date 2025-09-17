"""
Обёртки над Chrome DevTools Protocol (CDP) для работы с Trio:
- Поиск и взаимодействие с DOM (CSS/XPath/теневые корни)
- Синтетический ввод (мышь/тач/клавиатура)
- Ожидание событий с таймаутами и фильтрами
"""

from contextlib import nullcontext
import logging
import time
from random import choice, choices, gauss, randint, uniform
from trio import move_on_after
from trio_cdp import dom, input_, open_cdp, page, target
import re
from utils import *

logger = logging.getLogger('magicstore')



def dict_slice(d, keys):
    return {k: d[k] for k in keys if k in d}


async def dispatch_key_press(key, sleep=0.2, **kvargs):
    """Отправить нажатие клавиши с опциональной вставкой символа.

    key: имя клавиши (например, 'Enter').
    text/unmodified_text: можно передать текст символа для события 'char'.
    """
    logger.debug("Press key: %s", key)
    kv1 = {k: kvargs[k] for k in ['text', 'unmodified_text'] if k in kvargs}
    await input_.dispatch_key_event('keyDown', key=key)
    if sleep: time.sleep(sleep)
    if len(kv1) > 0:
        await input_.dispatch_key_event('char', key=key, **kv1)
        if sleep: time.sleep(sleep)
    await input_.dispatch_key_event('keyUp', key=key)


async def click_node(node, focus=True, type='mouse', name='', count=1,
                     send_text=False, **kvargs):
    """Клик по узлу: мышь/тач или нажатие Enter.

    focus: фокус на элемент перед действием.
    type: 'mouse' | 'touch' | 'enter'.
    name: метка для логов.
    count: количество кликов (для мыши).
    """
    logger.info('Click node: %s %s %s', name, node, type)
    if focus: await dom.focus(node)
    box = await dom.get_box_model(node)
    [x0, y0], [x1, y1] = box.content[0:2], box.content[4:6]
    x, y = uniform(x0, x1), uniform(y0, y1)
    if type == 'mouse':
        await input_.dispatch_mouse_event("mouseMoved", x, y)
        await input_.dispatch_mouse_event("mousePressed", x, y,
                                          click_count=count,
                                          button=input_.MouseButton.LEFT)
        time.sleep(abs(gauss(1, 0.5)))
        await input_.dispatch_mouse_event("mouseReleased", x, y,
                                          button=input_.MouseButton.LEFT)
    elif type == 'touch':
        await input_.dispatch_touch_event('touchStart', [input_.TouchPoint(x, y)])
        time.sleep(abs(gauss(1, 0.5)))
        await input_.dispatch_touch_event('touchEnd', [input_.TouchPoint(x, y)])
    elif type == 'enter':
        await dispatch_key_press('Enter', **{'text': '\r'} if send_text else {})


async def node_text(node):
    """Вернуть текстовое содержимое узла (без HTML-тегов)."""
    nid = ensure_node_id(node)
    return re.sub(r'<.+?>', '', await dom.get_outer_html(nid))


async def node_attributes(node):
    """Вернуть атрибуты узла в виде словаря."""
    attrs = await dom.get_attributes(node)
    return dict(zip(attrs[::2], attrs[1::2]))


async def find_tab(conn, query):
    """Найти вкладку по подстроке URL или по предикату."""
    print(query)
    fn = (lambda x: query in x.url) if isinstance(query, str) else query
    xs = (x.target_id for x in await target.get_targets() \
          if x.type_ == 'page' and fn(x))
    return next(xs, None)


async def find_or_create_tab(conn, query, url='about:blank', force_new_tab=False):
    """Найти вкладку по query либо создать новую (about:blank)."""
    if force_new_tab or not (target_id := await find_tab(conn, query)):
        logger.info('Creating new target')
        target_id = await target.create_target(url)
    else:
        await target.activate_target(target_id)
    return target_id


async def node_insert_text(node, text, press_enter=False):
    """Вставить текст в активное поле; опционально нажать Enter."""
    if node: await dom.focus(node)
    await input_.insert_text(text)
    if press_enter:
        await dispatch_key_press('Enter', text='\r', unmodified_text='\r')


class QuerySelectorError(RuntimeError):
    """Ошибка при поиске узла по селектору/параметрам."""
    pass


def ensure_node_id(x):
    """Вернуть `node_id` для объекта узла либо само значение, если это int."""
    return x.node_id if isinstance(x, dom.Node) else x


async def _query_selector_(fn, query, root=None, try_hard=False,
                           errorp=True, delay=1, **kvargs):
    """Универсальная обёртка поиска узла(ов) с повторами/таймаутами."""
    if not root:
        root = await dom.get_document()
    i, root_id = 0, ensure_node_id(root)
    while True:
        res = await fn(root_id, query)
        if not res and try_hard and try_hard is not (i := i + 1):
            time.sleep(delay)
        elif not res and errorp:
            raise QuerySelectorError(query)
        else:
            return res


def _query_selector_args_(x, *args, mode=None, **kvargs):
    """Распаковать позиционные аргументы для функций query_selector*."""
    match args:
        case []:
            return None, x, mode
        case [query]:
            return x, query, None
        case [query, mode]:
            return x, query, mode


async def query_selector_xpath(root, query, first_only=False):
    """Поиск узла(ов) по XPath через perform_search/get_search_results."""
    search_id, nres = await dom.perform_search(query)
    if nres > 0:
        n = 1 if first_only else nres
        res = await dom.get_search_results(search_id, 0, n)
        return res[0] if first_only else res
    else:
        return None


async def query_selector(query, *args, **kvargs):
    """Поиск первого подходящего узла по CSS/XPath.

    Поддерживает формы вызова: (root, query, mode='xpath'|'css') или (query).
    """
    [root, query, mode] = _query_selector_args_(query, *args, **kvargs)
    match mode or 'css':
        case 'css':
            fn = dom.query_selector
        case 'xpath':
            fn = lambda r, q: query_selector_xpath(r, q, True)
    return await _query_selector_(fn, query, root, **kvargs)


async def query_selector_all(query, *args, **kvargs):
    """Поиск всех подходящих узлов по CSS/XPath."""
    [root, query, mode] = _query_selector_args_(query, *args, **kvargs)
    match mode or 'css':
        case 'css':
            fn = dom.query_selector_all
        case 'xpath':
            fn = query_selector_xpath
    return await _query_selector_(fn, query, root, **kvargs)


async def query_selector_shadow(root, queries, **kvargs):
    """Поиск узла в цепочке теневых корней: ['w3m-modal', ..., 'button']."""
    match queries:
        case [q]:
            return await query_selector(root, q, **kvargs)
        case [q, *qs]:
            node_id = await query_selector(root, q, **kvargs)
            node = await dom.describe_node(node_id)
            shadow_id = node.shadow_roots[0].backend_node_id
            obj = await dom.resolve_node(backend_node_id=shadow_id)
            shadow_root = await dom.request_node(obj.object_id)
            return await query_selector_shadow(shadow_root, qs, **kvargs)


async def query_and_click_node(query, *args, **kvargs):
    """Найти узел по селектору и кликнуть по нему (если найден)."""
    node = await query_selector(query, *args, **kvargs)
    node and await click_node(node, **kvargs)
    return node


def maybe_move_on_after(timeout):
    """Вернуть контекст-менеджер таймаута либо пустой контекст, если timeout=None."""
    class Empty: pass
    if timeout:
        ctxmgr = move_on_after(timeout)
    else:
        obj = Empty()
        obj.cancelled_caught = False
        ctxmgr = nullcontext(obj)
    return ctxmgr


async def afind(aiter, pred, each=None, k=1, timeout=None,
                error_msg='Timeout in afind', noerror=False,
                default=None):
    """Найти k‑е событие в асинхронном итерируемом, удовлетворяющее предикату.

    timeout: секунды; noerror=True — вернуть default вместо исключения.
    """
    with maybe_move_on_after(timeout) as scope:
        i = 0
        async for x in aiter:
            if each: each(x)
            if pred(x) and (i := i + 1) == k:
                break
    if scope.cancelled_caught:
        if noerror:
            return default
        else:
            raise TimeoutError(error_msg)
    else:
        return x
