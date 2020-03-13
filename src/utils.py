import csv
from typing import List, Dict, Tuple, IO
import functools
from discord.ext import commands
import datetime as dt
import time
import json
import os
import asyncio
from decouple import config
from aiohttp import ClientSession
import aiofiles


URI_DATA      = config("uri_data")
DATA_PATH     = "data/datas.json"
CSV_DATA_PATH = "data/parsed_csv.json"
NEWS_PATH     = "data/news.json"

COLOR         = 0x5A12DF
DISCORD_LIMIT = 2 ** 11 # discord limit 2048
USER_AGENT    = {'User-Agent': 'Mozilla/5.0 (X11; Linux i586; rv:31.0) Gecko/20100101 Firefox/73.0'}

_CONFIRMED_URI  = "https://raw.githubusercontent.com/CSSEGISandData/COVID-19/master/csse_covid_19_data/csse_covid_19_time_series/time_series_19-covid-Confirmed.csv"
_DEATH_URI      = "https://raw.githubusercontent.com/CSSEGISandData/COVID-19/master/csse_covid_19_data/csse_covid_19_time_series/time_series_19-covid-Deaths.csv"
_RECOVERED_URI  = "https://raw.githubusercontent.com/CSSEGISandData/COVID-19/master/csse_covid_19_data/csse_covid_19_time_series/time_series_19-covid-Recovered.csv"
_CONFIRMED_PATH = "data/time_series_19-covid-Confirmed.csv"
_DEATH_PATH     = "data/time_series_19-covid-Deaths.csv"
_RECOVERED_PATH = "data/time_series_19-covid-Recovered.csv"


def csv_parse():
    dic = {}
    t, r, d = 0, 0, 0
    confirmed_data = data_reader(_CONFIRMED_PATH)
    recovered_data = data_reader(_RECOVERED_PATH)
    deaths_data = data_reader(_DEATH_PATH)
    lk = last_key(confirmed_data)
    for data in confirmed_data:
        i = 0
        current_country = data["Country/Region"]
        if current_country == "US":
            current_country = "United States"
        if current_country not in dic:
            dic[current_country] = {
                "confirmed": int(data[lk]),
                "recovered": 0,
                "deaths": 0
            }
        else:
            dic[current_country]["confirmed"] += int(data[lk])
        t += int(data[lk])

    for data in recovered_data:
        i = 0
        current_country = data["Country/Region"]
        if current_country == "US":
            current_country = "United States"

        dic[current_country]["recovered"] += int(data[lk])
        r += int(data[lk])

    for data in deaths_data:
        i = 0
        current_country = data["Country/Region"]
        if current_country == "US":
            current_country = "United States"

        dic[current_country]["deaths"] += int(data[lk])
        d += int(data[lk])

    dic["total"] = {
        "confirmed": t,
        "recovered": r,
        "deaths": d
    }

    with open(CSV_DATA_PATH, "w") as f:
        f.write(json.dumps(dic, indent=4))

def matching_path(fpath: str):
    fpath = fpath.split("-")
    return fpath[2].lower()[:-4]

def from_json(fpath: str) -> dict:
    with open(fpath, "r") as f:
        jso = json.load(f)
    return jso

def difference_on_update(old_data: dict, new_data: dict):
    old_c = old_data["total"]["confirmed"]
    old_r = old_data["total"]["recovered"]
    old_d = old_data["total"]["deaths"]
    new_c = new_data["total"]["confirmed"]
    new_r = new_data["total"]["recovered"]
    new_d = new_data["total"]["deaths"]
    return new_c - old_c, new_r - old_r, new_d - old_d

def diff_confirmed(csv: dict, k: str, v: dict, key_getter: str) -> int:
    if type(csv) == list:
        return v[key_getter]
    for c, val in csv.items():
        if c == k:
            return int(v[key_getter]) - int(val[key_getter])
    return v[key_getter]

def string_formatting(data_parsed: dict, param: list=[]) -> Tuple[str, str]:
    tot = data_parsed["total"]
    max_length = DISCORD_LIMIT - 80
    length = 0
    old_text = ""
    text = ""
    d = {}
    header = "Confirmed **{}** [+**{}**]\nRecovered **{}** ({}) [+**{}**]\nDeaths **{}** ({}) [+**{}**]\n"
    header_length = len(header)
    param_length = len(param)
    my_csv = from_json(CSV_DATA_PATH)
    if param_length:
        for p in param:
            p = p.lower()
            p_length = len(p)
            for k, v in data_parsed["data"].items():
                try:
                    country = v["country"]["name"] if v["country"]["name"] is not None else "."
                    code = v['country']['code'] if v["country"]["code"] is not None else "."
                    stats = v['statistics']
                    if (p_length == 2 and p == code.lower()):
                        text += f"**{country}** : {stats['confirmed']} confirmed [+**{diff_confirmed(my_csv, country, stats, 'confirmed')}**], {stats['recovered']} recovered [+**{diff_confirmed(my_csv, country, stats, 'recovered')}**], {stats['deaths']} deaths [+**{diff_confirmed(my_csv, country, stats, 'deaths')}**]\n"
                        length = len(text) + header_length
                        break
                    elif country.lower().startswith(p) and p_length != 2:
                        text += f"**{country}** : {stats['confirmed']} confirmed [+**{diff_confirmed(my_csv, country, stats, 'confirmed')}**], {stats['recovered']} recovered [+**{diff_confirmed(my_csv, country, stats, 'recovered')}**], {stats['deaths']} deaths [+**{diff_confirmed(my_csv, country, stats, 'deaths')}**]\n"
                        length = len(text) + header_length
                except KeyError:
                    pass
            if length < max_length:
                old_text = text
    else:
        for v in data_parsed["sorted"]:
            confirmed = v['statistics']['confirmed']
            country = v['country']['name'] if v["country"]["name"] is not None else "."
            stats = v['statistics']
            if stats['confirmed']:
                text += f"**{country}** {confirmed} [+{diff_confirmed(my_csv, country, v['statistics'], 'confirmed')}]\n"
                length = len(text) + header_length
            if length >= max_length:
                break
            else:
                old_text = text

    if length >= max_length:
        text = old_text
    t, r, c = difference_on_update(my_csv, data_parsed)
    header = header.format(
        tot["confirmed"],
        t,
        tot["recovered"],
        percentage(tot["confirmed"], tot["recovered"]),
        r,
        tot["deaths"],
        percentage(tot["confirmed"], tot["deaths"]),
        c
    )
    return header, text

def trigger_typing(func):
    @functools.wraps(func)
    async def wrapper(self, ctx: commands.Context, *args, **kwargs):
        await ctx.trigger_typing()
        return await func(self, ctx, *args, **kwargs)
    return wrapper

def data_reader(fpath: str) -> List[dict]:
    with open(fpath, "r") as f:
        cr = csv.DictReader(f.read().splitlines(), delimiter=',')
    return list(cr)

def discord_timestamp():
    return dt.datetime.utcfromtimestamp(time.time())

def last_key(csv_data: List[dict]) -> int:
    return list(csv_data[0].keys())[-1]

def last_update(fpath: str):
    lcu = dt.datetime.utcfromtimestamp(os.path.getctime(fpath))
    return f"Last update {lcu.strftime('%Y-%m-%d %H:%M:%S')} GMT +0000"

def percentage(total, x):
    return "{:.2f}%".format(x * 100 / total) if total > 0 else 0


class UpdateHandler:
    def __init__(self, lang="en"):
        self.news_api_key = config("news_api")
        self.q = "coronavirus covid 19"
        self.lang = lang
        self.update_list = self.update_list()

    def is_csv(self, path: str):
        return path[-4:] == ".csv"

    def update_list(self):
        return {
            f"http://newsapi.org/v2/top-headlines?apiKey={self.news_api_key}&language={self.lang}&q={self.q}": NEWS_PATH,
            config("uri_data"): DATA_PATH,
            _CONFIRMED_URI: _CONFIRMED_PATH,
            _RECOVERED_URI: _RECOVERED_PATH,
            _DEATH_URI: _DEATH_PATH
        }

    async def fetch(self, url: str, session: ClientSession, **kwargs):
        resp = await session.request(
            method="GET",
            url=url,
            **kwargs
        )
        try:
            data = await resp.json()
        except Exception as e:
            data = await resp.text()
        return data

    async def parse(self, url: str, session: ClientSession, **kwargs):
        resp = await self.fetch(url=url, session=session, **kwargs)
        if self.is_csv(url):
            return resp
        return json.dumps(resp, indent=4)

    async def _write(self, url:str, file: IO, session: ClientSession, **kwargs):
        to_write = await self.parse(url=url, session=session, **kwargs)
        if not to_write:
            return None
        async with aiofiles.open(file, "w+") as f:
            await f.write(to_write)

    async def update(self, **kwargs):
        async with ClientSession() as session:
            tasks = []
            for url, fpath in self.update_list.items():
                tasks.append(
                    self._write(url=url, file=fpath, session=session, **kwargs)
                )
            await asyncio.gather(*tasks)