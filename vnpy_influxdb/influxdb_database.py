""""""
from datetime import datetime
from typing import List
import shelve

from influxdb import InfluxDBClient

from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.object import BarData, TickData
from vnpy.trader.database import (
    BaseDatabase,
    BarOverview,
    DB_TZ,
    convert_tz
)
from vnpy.trader.setting import SETTINGS
from vnpy.trader.utility import (
    generate_vt_symbol,
    extract_vt_symbol,
    get_file_path
)


class InfluxdbDatabase(BaseDatabase):
    """InfluxDB数据库接口"""
    overview_filename = "influxdb_overview"
    overview_filepath = str(get_file_path(overview_filename))

    def __init__(self) -> None:
        """"""
        database = SETTINGS["database.database"]
        user = SETTINGS["database.user"]
        password = SETTINGS["database.password"]
        host = SETTINGS["database.host"]
        port = SETTINGS["database.port"]

        self.client = InfluxDBClient(host, port, user, password, database)
        self.client.create_database(database)

    def save_bar_data(self, bars: List[BarData]) -> bool:
        """保存K线数据"""
        json_body = []
        # 读取主键参数
        bar = bars[0]
        vt_symbol = bar.vt_symbol
        interval = bar.interval

        # 将BarData数据转换为字典，并调整时区
        for bar in bars:
            bar.datetime = convert_tz(bar.datetime)

            d = {
                "measurement": "bar_data",
                "tags": {
                    "vt_symbol": vt_symbol,
                    "interval": interval.value
                },
                "time": bar.datetime.isoformat(),
                "fields": {
                    "open_price": bar.open_price,
                    "high_price": bar.high_price,
                    "low_price": bar.low_price,
                    "close_price": bar.close_price,
                    "volume": bar.volume,
                    "turnover": bar.turnover,
                    "open_interest": bar.open_interest,
                }
            }
            json_body.append(d)

        self.client.write_points(json_body, batch_size=10000)

        # 更新K线汇总数据
        symbol, exchange = extract_vt_symbol(vt_symbol)
        key = f"{vt_symbol}_{interval.value}"

        f = shelve.open(self.overview_filepath)
        overview = f.get(key, None)

        if not overview:
            overview = BarOverview(
                symbol=symbol,
                exchange=exchange,
                interval=interval
            )
            overview.count = len(bars)
            overview.start = bars[0].datetime
            overview.end = bars[-1].datetime
        else:
            overview.start = min(overview.start, bars[0].datetime)
            overview.end = max(overview.end, bars[-1].datetime)

            query = (
                "select count(close_price) from bar_data"
                " where vt_symbol=$vt_symbol"
                " and interval=$interval"
            )
            bind_params = {
                "vt_symbol": vt_symbol,
                "interval": interval.value
            }
            result = self.client.query(query, bind_params=bind_params)
            points = result.get_points()

            for d in points:
                overview.count = d["count"]

        f[key] = overview
        f.close()

    def save_tick_data(self, ticks: List[TickData]) -> bool:
        """保存TICK数据"""
        json_body = []

        tick = ticks[0]
        vt_symbol = tick.vt_symbol

        for tick in ticks:
            tick.datetime = convert_tz(tick.datetime)

            d = {
                "measurement": "tick_data",
                "tags": {
                    "vt_symbol": vt_symbol
                },
                "time": tick.datetime.isoformat(),
                "fields": {
                    "name": tick.name,
                    "volume": tick.volume,
                    "turnover": tick.turnover,
                    "open_interest": tick.open_interest,
                    "last_price": tick.last_price,
                    "last_volume": tick.last_volume,
                    "limit_up": tick.limit_up,
                    "limit_down": tick.limit_down,

                    "open_price": tick.open_price,
                    "high_price": tick.high_price,
                    "low_price": tick.low_price,
                    "pre_close": tick.pre_close,

                    "bid_price_1": tick.bid_price_1,
                    "bid_price_2": tick.bid_price_2,
                    "bid_price_3": tick.bid_price_3,
                    "bid_price_4": tick.bid_price_4,
                    "bid_price_5": tick.bid_price_5,

                    "ask_price_1": tick.ask_price_1,
                    "ask_price_2": tick.ask_price_2,
                    "ask_price_3": tick.ask_price_3,
                    "ask_price_4": tick.ask_price_4,
                    "ask_price_5": tick.ask_price_5,

                    "bid_volume_1": tick.bid_volume_1,
                    "bid_volume_2": tick.bid_volume_2,
                    "bid_volume_3": tick.bid_volume_3,
                    "bid_volume_4": tick.bid_volume_4,
                    "bid_volume_5": tick.bid_volume_5,

                    "ask_volume_1": tick.ask_volume_1,
                    "ask_volume_2": tick.ask_volume_2,
                    "ask_volume_3": tick.ask_volume_3,
                    "ask_volume_4": tick.ask_volume_4,
                    "ask_volume_5": tick.ask_volume_5,

                    "localtime": tick.localtime
                }
            }
            json_body.append(d)

        self.client.write_points(json_body, batch_size=10000)

    def load_bar_data(
        self,
        symbol: str,
        exchange: Exchange,
        interval: Interval,
        start: datetime,
        end: datetime
    ) -> List[BarData]:
        """读取K线数据"""
        query = (
            "select * from bar_data"
            " where vt_symbol=$vt_symbol"
            " and interval=$interval"
            f" and time >= '{start.date().isoformat()}'"
            f" and time <= '{end.date().isoformat()}';"
        )

        bind_params = {
            "vt_symbol": generate_vt_symbol(symbol, exchange),
            "interval": interval.value
        }

        result = self.client.query(query, bind_params=bind_params)
        points = result.get_points()

        bars: List[BarData] = []
        for d in points:
            dt = datetime.strptime(d["time"], "%Y-%m-%dT%H:%M:%SZ")

            bar = BarData(
                symbol=symbol,
                exchange=exchange,
                interval=interval,
                datetime=datetime.fromtimestamp(dt.timestamp(), DB_TZ),
                open_price=d["open_price"],
                high_price=d["high_price"],
                low_price=d["low_price"],
                close_price=d["close_price"],
                volume=d["volume"],
                turnover=d["turnover"],
                open_interest=d["open_interest"],
                gateway_name="DB"
            )
            bars.append(bar)

        return bars

    def load_tick_data(
        self,
        symbol: str,
        exchange: Exchange,
        start: datetime,
        end: datetime
    ) -> List[TickData]:
        """读取TICK数据"""
        query = (
            "select * from tick_data"
            " where vt_symbol=$vt_symbol"
            f" and time >= '{start.date().isoformat()}'"
            f" and time <= '{end.date().isoformat()}';"
        )

        bind_params = {
            "vt_symbol": generate_vt_symbol(symbol, exchange),
        }

        result = self.client.query(query, bind_params=bind_params)
        points = result.get_points()

        ticks: List[TickData] = []
        for d in points:
            dt = datetime.strptime(d["time"], "%Y-%m-%dT%H:%M:%SZ")

            tick = TickData(
                symbol=symbol,
                exchange=exchange,
                datetime=datetime.fromtimestamp(dt.timestamp(), DB_TZ),
                name=d["name"],
                volume=d["volume"],
                turnover=d["turnover"],
                open_interest=d["open_interest"],
                last_price=d["last_price"],
                last_volume=d["last_volume"],
                limit_up=d["limit_up"],
                limit_down=d["limit_down"],
                open_price=d["open_price"],
                high_price=d["high_price"],
                low_price=d["low_price"],
                pre_close=d["pre_close"],
                bid_price_1=d["bid_price_1"],
                bid_price_2=d["bid_price_2"],
                bid_price_3=d["bid_price_3"],
                bid_price_4=d["bid_price_4"],
                bid_price_5=d["bid_price_5"],
                ask_price_1=d["ask_price_1"],
                ask_price_2=d["ask_price_2"],
                ask_price_3=d["ask_price_3"],
                ask_price_4=d["ask_price_4"],
                ask_price_5=d["ask_price_5"],
                bid_volume_1=d["bid_volume_1"],
                bid_volume_2=d["bid_volume_2"],
                bid_volume_3=d["bid_volume_3"],
                bid_volume_4=d["bid_volume_4"],
                bid_volume_5=d["bid_volume_5"],
                ask_volume_1=d["ask_volume_1"],
                ask_volume_2=d["ask_volume_2"],
                ask_volume_3=d["ask_volume_3"],
                ask_volume_4=d["ask_volume_4"],
                ask_volume_5=d["ask_volume_5"],
                localtime=d["localtime"],
                gateway_name="DB"
            )
            ticks.append(tick)

        return ticks

    def delete_bar_data(
        self,
        symbol: str,
        exchange: Exchange,
        interval: Interval
    ) -> int:
        """删除K线数据"""
        bind_params = {
            "vt_symbol": generate_vt_symbol(symbol, exchange),
            "interval": interval.value
        }

        # 查询数量
        query1 = (
            "select count(close_price) from bar_data"
            " where vt_symbol=$vt_symbol"
            " and interval=$interval"
        )
        result = self.client.query(query1, bind_params=bind_params)
        points = result.get_points()

        for d in points:
            count = d["count"]

        # 删除K线数据
        query2 = (
            "drop series from bar_data"
            " where vt_symbol=$vt_symbol"
            " and interval=$interval"
        )
        self.client.query(query2, bind_params=bind_params)

        # 删除K线汇总数据
        f = shelve.open(self.overview_filepath)
        vt_symbol = generate_vt_symbol(symbol, exchange)
        key = f"{vt_symbol}_{interval.value}"
        if key in f:
            f.pop(key)
        f.close()

        return count

    def delete_tick_data(
        self,
        symbol: str,
        exchange: Exchange
    ) -> int:
        """删除TICK数据"""
        bind_params = {
            "vt_symbol": generate_vt_symbol(symbol, exchange),
        }

        # 查询TICK数量
        query1 = (
            "select count(last_price) from tick_data"
            " where vt_symbol=$vt_symbol"
        )
        result = self.client.query(query1, bind_params=bind_params)
        points = result.get_points()

        for d in points:
            count = d["count"]

        # 删除TICK数据
        query2 = (
            "drop series from tick_data"
            " where vt_symbol=$vt_symbol"
        )
        self.client.query(query2, bind_params=bind_params)

        return count

    def get_bar_overview(self) -> List[BarOverview]:
        """查询数据库中的K线汇总信息"""
        # 如果已有K线，但缺失汇总信息，则执行初始化
        query = "select count(close_price) from bar_data"
        result = self.client.query(query)
        points = result.get_points()
        data_count = 0
        for d in points:
            data_count = d["count"]

        f = shelve.open(self.overview_filepath)
        overview_count = len(f)

        if data_count and not overview_count:
            self.init_bar_overview()

        overviews = list(f.values())
        f.close()
        return overviews

    def init_bar_overview(self) -> None:
        """初始化数据库中的K线汇总信息"""
        f = shelve.open(self.overview_filepath)

        query: str = "select count(close_price) from bar_data group by *"
        result = self.client.query(query)

        for k, v in result.items():
            tags = k[1]
            data = list(v)[0]

            vt_symbol = tags["vt_symbol"]
            symbol, exchange = extract_vt_symbol(vt_symbol)
            interval = Interval(tags["interval"])

            overview = BarOverview(
                symbol=symbol,
                exchange=exchange,
                interval=interval,
                count=data["count"]
            )
            overview.start = self.get_bar_datetime(vt_symbol, interval, 1)
            overview.end = self.get_bar_datetime(vt_symbol, interval, -1)

            key = f"{vt_symbol}_{interval.value}"
            f[key] = overview

        f.close()

    def get_bar_datetime(self, vt_symbol: str, interval: Interval, order: int) -> datetime:
        """获取K线数据起始或结束时间"""
        if order > 0:
            keyword = "first"
        else:
            keyword = "last"

        query = (
            f"select {keyword}(close_price), * from bar_data"
            " where vt_symbol=$vt_symbol"
            " and interval=$interval"
        )

        bind_params = {
            "vt_symbol": vt_symbol,
            "interval": interval.value
        }

        result = self.client.query(query, bind_params=bind_params)
        points = result.get_points()

        for d in points:
            dt = datetime.strptime(d["time"], "%Y-%m-%dT%H:%M:%SZ")

        return dt
