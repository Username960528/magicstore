#!/usr/bin/env python3

import json
import logging
from collections import Counter, defaultdict
#from fcntl import LOCK_EX, LOCK_SH, LOCK_UN, lockf
from portalocker import LOCK_EX, LOCK_SH, unlock, lock
from itertools import pairwise
from random import choice, choices, randint
from unicodedata import normalize

import requests
from trio_cdp import dom, input_, open_cdp, page, target

#from cdp_utils import *


logger = logging.getLogger('magicstore')


ACCOUNTS = {}


class TimeoutError(RuntimeError):
    pass


class MarkovGenerator:
    def __init__(self):
        self.table = defaultdict(Counter)

    def add_seq(self, seq):
        for x, y in pairwise(['START'] + list(seq) + ['END']):
            self.table[x][y] += 1

    def generate(self, max_length=None, min_length=1):
        x, seq = 'START', []
        while True:
            [ x ] = choices(list(self.table[x].keys()),
                            list(self.table[x].values()), k=1)
            if x == 'END':
                return ''.join(seq) if len(seq) > min_length else self.generate(max_length, min_length)
            elif max_length and len(seq) > max_length:
                return self.generate(max_length, min_length)
            else:
                seq.append(x)


def load_dictionary(path):
    words = { 'nouns': [], 'adjs': [] }
    types = { 'm.': 'nouns', 'm.anim.': 'nouns', 'adj.': 'adjs' }
    with open(path, encoding='utf-8') as dictfile:
        for x in json.load(dictfile)['wordList']:
            if ' ' in x[1]: continue
            word = normalize('NFKD', x[1]).encode('ASCII', 'ignore')
            try:
                words[types[x[3]]].append(str(word, encoding='ASCII'))
            except KeyError: pass
    return words


def generate_username(words):
    noun = choice(words['nouns']).capitalize()
    adj  = choice(words['adjs']).capitalize()
    return adj + noun


ADS_BASE_URI = "http://local.adspower.net:50325"
def ads_request(method, **kvargs):
    resp = requests.get(ADS_BASE_URI + method, params=kvargs)
    json = resp.json()
    if json['code'] == 0:
        return json.get('data')
    else:
        raise RuntimeError(json['msg'])


def find_unused_wallet():
    used_ones, wallets = [], ACCOUNTS['wallet']
    for x in ACCOUNTS['account'].values():
        if val := x.get('wallet', {}).get('id'):
            used_ones += [val]
    x = next(filter(lambda x: x not in used_ones, wallets.keys()))
    return x, wallets[x]


def update_account(info):
    with open('alltheshit.json', 'r+') as jfile:
        lock(jfile, LOCK_EX)
        ACCOUNTS = json.load(jfile)
        ACCOUNTS['account'][info['serial_number']] |= info
        try:
            jfile.seek(0)
            json.dump(ACCOUNTS, jfile)
            jfile.truncate()
        finally:
            unlock(jfile)


def generate_password(min_length=8, max_length=10, chars='1234567890'):
    length = randint(min_length, max_length)
    return ''.join(choices(chars, k=length))
