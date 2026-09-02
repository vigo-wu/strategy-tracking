# coding: utf-8
"""把本地回测成交写成国金「操作明细」同款 CSV。"""
from __future__ import annotations

import csv
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any


HEADER = (
    "代码",
    "名称",
    "品种类型",
    "行业",
    "多空",
    "操作时间",
    "操作类型",
    "操作价格",
    "当前价格",
    "盈利",
    "买入权重(%)",
    "当前权重(%)",
    "数量",
    "交易费用",
    "市值",
    "业务类型",
    "可部署资金",
    "组合权益",
)

# 与 hongli_band/回测记录 终端导出一致
STOCK_META = {
    "000001": ("平安银行", "股票", "银行"),
    "000002": ("万科A", "股票", "汽车"),
    "000063": ("中兴通讯", "股票", "通信"),
    "000069": ("华侨城A", "股票", "电力设备"),
    "000100": ("TCL科技", "股票", "电子"),
    "000157": ("中联重科", "股票", "汽车"),
    "000301": ("东方盛虹", "股票", "基础化工"),
    "000333": ("美的集团", "股票", "家用电器"),
    "000400": ("许继电气", "股票", "电力设备"),
    "000401": ("冀东水泥", "股票", "非银金融"),
    "000425": ("徐工机械", "股票", "机械设备"),
    "000538": ("云南白药", "股票", "计算机"),
    "000568": ("泸州老窖", "股票", "基础化工"),
    "000596": ("古井贡酒", "股票", "食品饮料"),
    "000625": ("长安汽车", "股票", "汽车"),
    "000630": ("铜陵有色", "股票", "基础化工"),
    "000651": ("格力电器", "股票", "家用电器"),
    "000661": ("长春高新", "股票", "医药生物"),
    "000708": ("中信特钢", "股票", "食品饮料"),
    "000725": ("京东方A", "股票", "电子"),
    "000728": ("国元证券", "股票", "食品饮料"),
    "000733": ("振华科技", "股票", "国防军工"),
    "000768": ("中航西飞", "股票", "国防军工"),
    "000776": ("广发证券", "股票", "有色金属"),
    "000786": ("北新建材", "股票", "建筑材料"),
    "000792": ("盐湖股份", "股票", "计算机"),
    "000858": ("五粮液", "股票", "食品饮料"),
    "000876": ("新希望", "股票", "计算机"),
    "000895": ("双汇发展", "股票", "食品饮料"),
    "000938": ("紫光股份", "股票", "食品饮料"),
    "000963": ("华东医药", "股票", "银行"),
    "000983": ("山西焦煤", "股票", "煤炭"),
    "000988": ("华工科技", "股票", "机械设备"),
    "001280": ("中国铀业", "股票", "银行"),
    "001979": ("招商蛇口", "股票", "房地产"),
    "002001": ("新和成", "股票", "医药生物"),
    "002007": ("华兰生物", "股票", "医药生物"),
    "002024": ("ST易购", "股票", "电力设备"),
    "002027": ("分众传媒", "股票", "基础化工"),
    "002032": ("苏泊尔", "股票", "家用电器"),
    "002044": ("美年健康", "股票", "医药生物"),
    "002049": ("紫光国微", "股票", "电子"),
    "002050": ("三花智控", "股票", "汽车"),
    "002064": ("华峰化学", "股票", "电子"),
    "002129": ("TCL中环", "股票", "电力设备"),
    "002142": ("宁波银行", "股票", "银行"),
    "002153": ("石基信息", "股票", "电力设备"),
    "002179": ("中航光电", "股票", "国防军工"),
    "002180": ("纳思达", "股票", "国防军工"),
    "002230": ("科大讯飞", "股票", "计算机"),
    "002236": ("大华股份", "股票", "电子"),
    "002241": ("歌尔股份", "股票", "非银金融"),
    "002252": ("上海莱士", "股票", "医药生物"),
    "002271": ("东方雨虹", "股票", "建筑材料"),
    "002311": ("海大集团", "股票", "汽车"),
    "002352": ("顺丰控股", "股票", "交通运输"),
    "002371": ("北方华创", "股票", "有色金属"),
    "002410": ("广联达", "股票", "计算机"),
    "002415": ("海康威视", "股票", "电子"),
    "002459": ("晶澳科技", "股票", "汽车"),
    "002460": ("赣锋锂业", "股票", "基础化工"),
    "002466": ("天齐锂业", "股票", "非银金融"),
    "002475": ("立讯精密", "股票", "电子"),
    "002493": ("荣盛石化", "股票", "基础化工"),
    "002497": ("雅化集团", "股票", "计算机"),
    "002555": ("三七互娱", "股票", "传媒"),
    "002594": ("比亚迪", "股票", "汽车"),
    "002601": ("龙佰集团", "股票", "基础化工"),
    "002602": ("世纪华通", "股票", "传媒"),
    "002648": ("卫星化学", "股票", "基础化工"),
    "002709": ("天赐材料", "股票", "电力设备"),
    "002714": ("牧原股份", "股票", "国防军工"),
    "002736": ("国信证券", "股票", "非银金融"),
    "002756": ("永兴材料", "股票", "有色金属"),
    "002812": ("恩捷股份", "股票", "电力设备"),
    "002821": ("凯莱英", "股票", "非银金融"),
    "002920": ("德赛西威", "股票", "汽车"),
    "002938": ("鹏鼎控股", "股票", "有色金属"),
    "003012": ("东鹏控股", "股票", "国防军工"),
    "003816": ("中国广核", "股票", "公用事业"),
    "300012": ("华测检测", "股票", "国防军工"),
    "300014": ("亿纬锂能", "股票", "电力设备"),
    "300015": ("爱尔眼科", "股票", "医药生物"),
    "300033": ("同花顺", "股票", "计算机"),
    "300034": ("钢研高纳", "股票", "银行"),
    "300059": ("东方财富", "股票", "非银金融"),
    "300124": ("汇川技术", "股票", "电力设备"),
    "300142": ("沃森生物", "股票", "医药生物"),
    "300144": ("宋城演艺", "股票", "食品饮料"),
    "300274": ("阳光电源", "股票", "电力设备"),
    "300347": ("泰格医药", "股票", "汽车"),
    "300408": ("三环集团", "股票", "电子"),
    "300413": ("快乐购", "股票", "传媒"),
    "300433": ("蓝思科技", "股票", "计算机"),
    "300450": ("先导智能", "股票", "电力设备"),
    "300496": ("中科创达", "股票", "计算机"),
    "300601": ("康泰生物", "股票", "食品饮料"),
    "300628": ("亿联网络", "股票", "通信"),
    "300661": ("圣邦股份", "股票", "电子"),
    "300750": ("宁德时代", "股票", "电力设备"),
    "300760": ("迈瑞医疗", "股票", "医药生物"),
    "300763": ("锦浪科技", "股票", "电力设备"),
    "300782": ("卓胜微", "股票", "电子"),
    "300832": ("新产业", "股票", "医药生物"),
    "300896": ("美畅股份", "股票", "基础化工"),
    "300957": ("贝泰妮", "股票", "电子"),
    "300999": ("金龙鱼", "股票", "电子"),
    "301165": ("锐捷网络", "股票", "汽车"),
    "301308": ("江波龙", "股票", "电子"),
    "513530": ("港股通红利ETF华泰柏瑞", "ETF", "其它"),
    "600000": ("浦发银行", "股票", "银行"),
    "600009": ("上海机场", "股票", "有色金属"),
    "600011": ("华能国际", "股票", "公用事业"),
    "600015": ("华夏银行", "股票", "银行"),
    "600016": ("民生银行", "股票", "银行"),
    "600019": ("宝钢股份", "股票", "钢铁"),
    "600025": ("华能水电", "股票", "公用事业"),
    "600028": ("中国石化", "股票", "石油石化"),
    "600029": ("南方航空", "股票", "交通运输"),
    "600030": ("中信证券", "股票", "非银金融"),
    "600031": ("三一重工", "股票", "机械设备"),
    "600036": ("招商银行", "股票", "银行"),
    "600048": ("保利发展", "股票", "房地产"),
    "600050": ("中国联通", "股票", "通信"),
    "600061": ("国投资本", "股票", "非银金融"),
    "600089": ("特变电工", "股票", "电力设备"),
    "600100": ("同方股份", "股票", "非银金融"),
    "600104": ("上汽集团", "股票", "汽车"),
    "600109": ("国金证券", "股票", "基础化工"),
    "600111": ("北方稀土", "股票", "有色金属"),
    "600115": ("中国东航", "股票", "交通运输"),
    "600118": ("中国卫星", "股票", "国防军工"),
    "600150": ("中国船舶", "股票", "国防军工"),
    "600176": ("中国巨石", "股票", "医药生物"),
    "600188": ("兖矿能源", "股票", "煤炭"),
    "600196": ("复星医药", "股票", "基础化工"),
    "600219": ("南山铝业", "股票", "有色金属"),
    "600233": ("圆通速递", "股票", "交通运输"),
    "600309": ("万华化学", "股票", "基础化工"),
    "600346": ("恒力石化", "股票", "基础化工"),
    "600350": ("山东高速", "股票", "交通运输"),
    "600362": ("江西铜业", "股票", "有色金属"),
    "600372": ("中航机载", "股票", "国防军工"),
    "600383": ("金地集团", "股票", "非银金融"),
    "600406": ("国电南瑞", "股票", "电力设备"),
    "600426": ("华鲁恒升", "股票", "有色金属"),
    "600438": ("通威股份", "股票", "电力设备"),
    "600519": ("贵州茅台", "股票", "食品饮料"),
    "600547": ("山东黄金", "股票", "有色金属"),
    "600570": ("恒生电子", "股票", "电力设备"),
    "600585": ("海螺水泥", "股票", "电力设备"),
    "600588": ("用友网络", "股票", "计算机"),
    "600600": ("青岛啤酒", "股票", "食品饮料"),
    "600606": ("绿地控股", "股票", "计算机"),
    "600660": ("福耀玻璃", "股票", "汽车"),
    "600674": ("川投能源", "股票", "公用事业"),
    "600690": ("海尔智家", "股票", "家用电器"),
    "600703": ("三安光电", "股票", "基础化工"),
    "600741": ("华域汽车", "股票", "汽车"),
    "600754": ("锦江酒店", "股票", "社会服务"),
    "600760": ("中航沈飞", "股票", "食品饮料"),
    "600795": ("国电电力", "股票", "公用事业"),
    "600803": ("新奥股份", "股票", "公用事业"),
    "600809": ("山西汾酒", "股票", "食品饮料"),
    "600837": ("海通证券", "股票", "有色金属"),
    "600845": ("宝信软件", "股票", "计算机"),
    "600875": ("东方电气", "股票", "电力设备"),
    "600886": ("国投电力", "股票", "公用事业"),
    "600887": ("伊利股份", "股票", "食品饮料"),
    "600893": ("航发动力", "股票", "国防军工"),
    "600895": ("张江高科", "股票", "房地产"),
    "600900": ("长江电力", "股票", "公用事业"),
    "600919": ("江苏银行", "股票", "银行"),
    "600926": ("杭州银行", "股票", "银行"),
    "600941": ("中国移动", "股票", "电力设备"),
    "600958": ("东方证券", "股票", "非银金融"),
    "600968": ("海油发展", "股票", "石油石化"),
    "600989": ("宝丰能源", "股票", "基础化工"),
    "601006": ("大秦铁路", "股票", "交通运输"),
    "601009": ("南京银行", "股票", "银行"),
    "601012": ("隆基绿能", "股票", "电力设备"),
    "601058": ("赛轮轮胎", "股票", "汽车"),
    "601066": ("中信建投", "股票", "非银金融"),
    "601088": ("中国神华", "股票", "煤炭"),
    "601100": ("天山铝业", "股票", "有色金属"),
    "601111": ("中国国航", "股票", "交通运输"),
    "601117": ("中国化学", "股票", "建筑装饰"),
    "601138": ("工业富联", "股票", "电子"),
    "601139": ("深圳燃气", "股票", "计算机"),
    "601155": ("新城控股", "股票", "医药生物"),
    "601166": ("兴业银行", "股票", "银行"),
    "601169": ("北京银行", "股票", "银行"),
    "601186": ("中国铁建", "股票", "建筑装饰"),
    "601211": ("国泰君安", "股票", "非银金融"),
    "601216": ("君正集团", "股票", "医药生物"),
    "601225": ("陕西煤业", "股票", "煤炭"),
    "601229": ("上海银行", "股票", "银行"),
    "601238": ("广汽集团", "股票", "汽车"),
    "601288": ("农业银行", "股票", "银行"),
    "601318": ("中国平安", "股票", "非银金融"),
    "601319": ("中国人保", "股票", "非银金融"),
    "601328": ("交通银行", "股票", "银行"),
    "601336": ("新华保险", "股票", "非银金融"),
    "601337": ("广晟有色", "股票", "非银金融"),
    "601360": ("三六零", "股票", "计算机"),
    "601377": ("兴业证券", "股票", "非银金融"),
    "601390": ("中国中铁", "股票", "建筑装饰"),
    "601398": ("工商银行", "股票", "银行"),
    "601601": ("中国太保", "股票", "非银金融"),
    "601607": ("上海医药", "股票", "医药生物"),
    "601615": ("明阳智能", "股票", "电力设备"),
    "601618": ("中国中冶", "股票", "建筑装饰"),
    "601628": ("中国人寿", "股票", "非银金融"),
    "601633": ("长城汽车", "股票", "电力设备"),
    "601668": ("中国建筑", "股票", "建筑装饰"),
    "601669": ("中国电建", "股票", "国防军工"),
    "601688": ("华泰证券", "股票", "非银金融"),
    "601689": ("拓普集团", "股票", "汽车"),
    "601698": ("中国卫通", "股票", "国防军工"),
    "601699": ("潞安环能", "股票", "煤炭"),
    "601727": ("上海电气", "股票", "基础化工"),
    "601766": ("中国中车", "股票", "机械设备"),
    "601788": ("光大证券", "股票", "非银金融"),
    "601800": ("中国交建", "股票", "建筑装饰"),
    "601816": ("京沪高铁", "股票", "交通运输"),
    "601818": ("光大银行", "股票", "银行"),
    "601838": ("成都银行", "股票", "银行"),
    "601857": ("中国石油", "股票", "石油石化"),
    "601868": ("中国能建", "股票", "食品饮料"),
    "601872": ("招商轮船", "股票", "交通运输"),
    "601877": ("正泰电器", "股票", "电力设备"),
    "601878": ("浙商证券", "股票", "汽车"),
    "601881": ("中国银河", "股票", "电子"),
    "601898": ("中煤能源", "股票", "煤炭"),
    "601899": ("紫金矿业", "股票", "有色金属"),
    "601901": ("方正证券", "股票", "非银金融"),
    "601919": ("中远海控", "股票", "交通运输"),
    "601939": ("建设银行", "股票", "银行"),
    "601966": ("玲珑轮胎", "股票", "汽车"),
    "601985": ("中国核电", "股票", "公用事业"),
    "601988": ("中国银行", "股票", "银行"),
    "601989": ("中国重工", "股票", "国防军工"),
    "601998": ("中信银行", "股票", "银行"),
    "603160": ("汇顶科技", "股票", "基础化工"),
    "603259": ("药明康德", "股票", "医药生物"),
    "603260": ("合盛硅业", "股票", "基础化工"),
    "603288": ("海天味业", "股票", "食品饮料"),
    "603392": ("万泰生物", "股票", "汽车"),
    "603501": ("韦尔股份", "股票", "电子"),
    "603659": ("璞泰来", "股票", "电力设备"),
    "603799": ("华友钴业", "股票", "有色金属"),
    "603806": ("福斯特", "股票", "有色金属"),
    "603833": ("欧派家居", "股票", "食品饮料"),
    "603899": ("晨光股份", "股票", "银行"),
    "603993": ("洛阳钼业", "股票", "有色金属"),
    "688005": ("容百科技", "股票", "计算机"),
    "688012": ("中微公司", "股票", "有色金属"),
    "688036": ("传音控股", "股票", "有色金属"),
    "688063": ("龙芯中科", "股票", "电子"),
    "688072": ("拓荆科技", "股票", "电子"),
    "688111": ("金山办公", "股票", "计算机"),
    "688126": ("沪硅产业", "股票", "电力设备"),
    "688183": ("生益电子", "股票", "汽车"),
    "688188": ("柏楚电子", "股票", "电力设备"),
    "688303": ("大全能源", "股票", "非银金融"),
    "688363": ("华熙生物", "股票", "医药生物"),
    "688396": ("华润微", "股票", "有色金属"),
    "688536": ("思瑞浦", "股票", "计算机"),
    "688561": ("奇安信", "股票", "基础化工"),
    "688599": ("天合光能", "股票", "电力设备"),
    "688777": ("中控技术", "股票", "非银金融"),
    "688981": ("中芯国际", "股票", "电子"),
}

def stock_meta(stock: str) -> tuple[str, str, str, str]:
    raw = str(stock or "").strip().upper()
    code = raw.split(".", 1)[0]
    name, kind, industry = STOCK_META.get(code, (code, "股票", "其它"))
    if code not in STOCK_META and (code.startswith("51") or code.startswith("56") or code.startswith("15")):
        kind = "ETF"
        industry = "其它"
    return code, name, kind, industry


def _fmt_time(when: Any) -> str:
    if when is None:
        return datetime.now().strftime("%Y-%m-%d 15:00:00")
    if hasattr(when, "strftime"):
        return when.strftime("%Y-%m-%d %H:%M:%S")
    digits = "".join(ch for ch in str(when) if ch.isdigit())
    if len(digits) >= 14:
        dt = datetime.strptime(digits[:14], "%Y%m%d%H%M%S")
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    if len(digits) >= 8:
        dt = datetime.strptime(digits[:8], "%Y%m%d")
        return dt.strftime("%Y-%m-%d 15:00:00")
    return str(when)


def _num(val: float, digits: int) -> str:
    return ("%." + str(int(digits)) + "f") % float(val)


def _pct(num: float, den: float) -> str:
    if den is None or float(den) <= 0:
        return "0.00%"
    return "%.2f%%" % (100.0 * float(num) / float(den))


class TradeLedger:
    """FIFO 持仓；买入盈利 0；卖出盈利 = 本笔成交实现盈亏。"""

    def __init__(self, stock: str):
        self.stock = str(stock or "").strip().upper()
        self.code, self.name, self.kind, self.industry = stock_meta(self.stock)
        self._px_digits = 3 if self.kind == "ETF" else 2
        self._lots: deque[dict] = deque()
        self.rows: list[list[str]] = []

    def on_buy(
        self,
        vol: int,
        price: float,
        when: Any,
        *,
        snap: dict[str, float] | None = None,
        snap_after: dict[str, float] | None = None,
        stock_mv: float | None = None,
    ) -> None:
        vol = int(vol)
        price = float(price)
        if vol < 100 or price <= 0:
            return
        self._lots.append({"shares": vol, "price": price})
        mv = float(price) * int(vol)
        if stock_mv is None:
            stock_mv = sum(int(l["shares"]) * float(l["price"]) for l in self._lots)
        self.rows.append(self._row("买入", when, price, vol, 0.0, snap, snap_after, mv, stock_mv))

    def on_sell(
        self,
        vol: int,
        price: float,
        when: Any,
        *,
        snap: dict[str, float] | None = None,
        snap_after: dict[str, float] | None = None,
        stock_mv: float | None = None,
    ) -> None:
        vol = int(vol)
        price = float(price)
        if vol < 100 or price <= 0:
            return
        remain = vol
        pnl = 0.0
        while remain > 0 and self._lots:
            lot = self._lots[0]
            take = min(int(lot["shares"]), remain)
            pnl += (price - float(lot["price"])) * take
            lot["shares"] = int(lot["shares"]) - take
            remain -= take
            if int(lot["shares"]) <= 0:
                self._lots.popleft()
        if stock_mv is None:
            stock_mv = sum(int(l["shares"]) * float(l["price"]) for l in self._lots)
        self.rows.append(self._row("卖出", when, price, vol, pnl, snap, snap_after, float(price) * vol, stock_mv))

    def _row(
        self,
        side: str,
        when: Any,
        price: float,
        vol: int,
        pnl: float,
        snap: dict[str, float] | None,
        snap_after: dict[str, float] | None,
        mv: float,
        stock_mv: float,
    ) -> list[str]:
        d = self._px_digits
        deploy = float((snap or {}).get("deploy_cap") or 0)
        eq_before = float((snap or {}).get("equity") or 0)
        eq_after = float((snap_after or {}).get("equity") or eq_before)
        if deploy > 0:
            buy_w = _pct(mv, deploy)
        else:
            buy_w = "0.00%"
        if eq_after > 0:
            cur_w = _pct(stock_mv, eq_after)
        else:
            cur_w = "0.00%"
        cap_s = _num(deploy, 2) if deploy > 0 else ""
        eq_s = _num(eq_after if snap_after else eq_before, 2) if (snap_after or snap) else ""
        return [
            self.code,
            self.name,
            self.kind,
            self.industry,
            "-",
            _fmt_time(when),
            side,
            _num(price, d),
            _num(price, d),
            _num(pnl, d),
            buy_w,
            cur_w,
            str(int(vol)),
            _num(0.0, d),
            _num(mv, d),
            side,
            cap_s,
            eq_s,
        ]

    def write(self, path: str | Path) -> Path:
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("w", encoding="gbk", newline="") as f:
            w = csv.writer(f)
            w.writerow(HEADER)
            w.writerows(self.rows)
        return dest


class CombinedTradeLedger:
    """组合回放：按当前激活标的写入同一明细表。"""

    def __init__(self, stock_getter):
        self._stock_getter = stock_getter
        self.rows: list[list[str]] = []
        self._lots: dict[str, deque] = {}

    def _ledger(self, stock: str) -> TradeLedger:
        lg = TradeLedger(stock)
        lg.rows = self.rows
        lg._lots = self._lots.setdefault(str(stock).strip().upper(), deque())
        return lg

    def on_buy(
        self,
        vol: int,
        price: float,
        when: Any,
        *,
        snap: dict[str, float] | None = None,
        snap_after: dict[str, float] | None = None,
        stock_mv: float | None = None,
        ns: dict | None = None,
    ) -> None:
        stock = str(self._stock_getter() or "").strip().upper()
        if not stock:
            return
        if stock_mv is None and ns is not None:
            from compound_wallet import _pos_dict_mv  # noqa: WPS433

            stock_mv = _pos_dict_mv(getattr(ns.get("A"), "position", None))
        self._ledger(stock).on_buy(
            vol,
            price,
            when,
            snap=snap,
            snap_after=snap_after,
            stock_mv=stock_mv,
        )

    def on_sell(
        self,
        vol: int,
        price: float,
        when: Any,
        *,
        snap: dict[str, float] | None = None,
        snap_after: dict[str, float] | None = None,
        stock_mv: float | None = None,
        ns: dict | None = None,
    ) -> None:
        stock = str(self._stock_getter() or "").strip().upper()
        if not stock:
            return
        if stock_mv is None and ns is not None:
            from compound_wallet import _pos_dict_mv  # noqa: WPS433

            stock_mv = _pos_dict_mv(getattr(ns.get("A"), "position", None))
        self._ledger(stock).on_sell(
            vol,
            price,
            when,
            snap=snap,
            snap_after=snap_after,
            stock_mv=stock_mv,
        )

    def write(self, path: str | Path) -> Path:
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("w", encoding="gbk", newline="") as f:
            w = csv.writer(f)
            w.writerow(HEADER)
            w.writerows(self.rows)
        return dest


def wrap_fill_hooks(
    ns: dict,
    ledger: TradeLedger | CombinedTradeLedger,
    wallet: Any | None = None,
) -> None:
    orig_buy = ns["_apply_buy_fill"]
    orig_sell = ns["_apply_sell_fill"]

    def _snap_before():
        if wallet is not None and wallet.enabled:
            return wallet.snapshot(ns)
        return None

    def _buy(vol, price, opened_at, **extra):
        snap = _snap_before()
        orig_buy(vol, price, opened_at, **extra)
        if wallet is not None and wallet.enabled:
            wallet.on_buy(vol, price)
        snap_after = _snap_before()
        kw: dict[str, Any] = {"snap": snap, "snap_after": snap_after}
        if isinstance(ledger, CombinedTradeLedger):
            kw["ns"] = ns
        ledger.on_buy(vol, price, opened_at, **kw)

    def _sell(now, reason, last_hint, filled_vol, mark_half=False, lot_ids=None):
        snap = _snap_before()
        orig_sell(
            now,
            reason,
            last_hint,
            filled_vol,
            mark_half=mark_half,
            lot_ids=lot_ids,
        )
        if wallet is not None and wallet.enabled:
            wallet.on_sell(filled_vol, last_hint)
        snap_after = _snap_before()
        kw: dict[str, Any] = {"snap": snap, "snap_after": snap_after}
        if isinstance(ledger, CombinedTradeLedger):
            kw["ns"] = ns
        ledger.on_sell(filled_vol, last_hint, now, **kw)

    ns["_apply_buy_fill"] = _buy
    ns["_apply_sell_fill"] = _sell


def trades_csv_path(log_path: Path) -> Path:
    return log_path.with_name(log_path.stem + "_操作明细.csv")
