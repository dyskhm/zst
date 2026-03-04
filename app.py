"""
基金净值走势可视化工具

功能描述:
    本脚本从东方财富网基金数据中心抓取指定基金的历史净值数据，
    经过数据处理后生成交互式的净值走势图网页（HTML格式）。

主要特性:
    1. 支持多基金品种同时展示和对比
    2. 自动从网络获取最新净值数据
    3. 生成可交互的图表（支持缩放、悬停查看详情）
    4. 完善的错误处理和日志记录
    5. 支持主备两套基金配置灵活切换

使用方式:
    直接运行: python app.py
    生成的文件: index.html（项目根目录）

作者: Auto-generated
版本: 2.0
"""

import os
import re
import json
import logging
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime

import requests
import pandas as pd
from pyecharts import options as opts
from pyecharts.charts import Line
from pyecharts.globals import ThemeType


# =============================================================================
# 日志配置
# =============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FundDataFetcher:
    """
    基金数据获取器

    负责从东方财富网API获取基金净值数据。
    实现了动态回调函数生成、请求参数构建、响应解析等功能。

    接口说明:
        - 接口地址: http://api.fund.eastmoney.com/f10/lsjz
        - 返回格式: JSONP格式，需要提取内层JSON数据
        - 数据频率: 每个交易日更新
        - 数据字段: FSRQ(日期), DWJZ(单位净值), ACCUM(累计净值)等
    """

    BASE_URL = "http://api.fund.eastmoney.com/f10/lsjz"

    DEFAULT_HEADERS = {
        'Referer': 'http://fundf10.eastmoney.com/',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    DEFAULT_PAGE_SIZE = 60

    REQUEST_INTERVAL = 0.5

    _last_request_time = 0.0

    @classmethod
    def _generate_timestamp(cls) -> Tuple[int, str]:
        """
        生成时间戳和回调函数字符串

        生成符合东方财富API要求的回调函数格式。
        回调函数名格式: jQuery_{timestamp}_{sequence}

        Returns:
            Tuple[时间戳, 回调函数名字符串]
        """
        timestamp = int(datetime.now().timestamp() * 1000)
        sequence = timestamp + 1000
        callback = f"jQuery_{timestamp}_{sequence}"
        return timestamp, callback

    @classmethod
    def _ensure_request_interval(cls) -> None:
        """
        确保请求间隔

        控制请求频率，避免被服务器封禁。
        每次请求前等待足够的时间间隔。
        """
        current_time = datetime.now().timestamp()
        elapsed = current_time - cls._last_request_time
        if elapsed < cls.REQUEST_INTERVAL:
            sleep_time = cls.REQUEST_INTERVAL - elapsed
            import time
            time.sleep(sleep_time)
        cls._last_request_time = datetime.now().timestamp()

    @classmethod
    def get_fund_nav_data(cls, code: str, page_size: int = DEFAULT_PAGE_SIZE) -> Optional[List[Dict[str, Any]]]:
        """
        获取指定基金的净值历史数据

        Args:
            code: 基金代码，6位数字字符串，如 '510310'
            page_size: 每次请求返回的记录数量，默认60条（约3个月数据）

        Returns:
            成功返回净值记录列表，每条记录包含日期(FSRQ)、单位净值(DWJZ)等字段
            失败返回 None

        Raises:
            网络异常: 打印警告并返回 None
            数据解析异常: 打印错误信息并返回 None
        """
        cls._ensure_request_interval()

        timestamp, callback = cls._generate_timestamp()

        params = {
            'callback': callback,
            'fundCode': code,
            'pageIndex': 1,
            'pageSize': page_size,
            'startDate': '',
            'endDate': '',
            '_': timestamp
        }

        try:
            response = requests.get(
                cls.BASE_URL,
                params=params,
                headers=cls.DEFAULT_HEADERS,
                timeout=10
            )
            response.raise_for_status()

            json_match = re.search(r'\((.*?)\)', response.text)
            if not json_match:
                logger.warning(f"基金 {code}: 无法解析返回数据，数据格式异常")
                return None

            data = json.loads(json_match.group(1))

            if data.get("ErrCode") != 0:
                logger.warning(f"基金 {code}: API返回错误 - {data.get('ErrMsg', '未知错误')}")
                return None

            return data.get("Data", {}).get("LSJZList", [])

        except requests.RequestException as e:
            logger.error(f"基金 {code}: 网络请求失败 - {str(e)}")
            return None
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"基金 {code}: 数据解析失败 - {str(e)}")
            return None
        except Exception as e:
            logger.error(f"基金 {code}: 未知错误 - {str(e)}")
            return None


class FundDataProcessor:
    """
    基金数据处理器

    负责基金数据的批量获取、格式转换和对齐处理。
    确保不同基金的数据按日期正确对齐。
    """

    @classmethod
    def fetch_multiple_funds_data(cls, fund_codes: List[str]) -> Tuple[Dict[int, str], Dict[str, Dict[int, float]]]:
        """
        批量获取多个基金的净值数据

        Args:
            fund_codes: 基金代码列表

        Returns:
            Tuple[日期字典, 基金净值字典]
            - 日期字典: {索引: 日期字符串}，所有基金共享相同的日期索引
            - 基金净值字典: {基金代码: {索引: 净值}}，按索引与日期字典对齐

        数据对齐说明:
            由于不同基金交易日可能不同（节假日休市），
            采用反向遍历方式，从最新数据开始填充索引，
            确保所有基金使用相同的日期序列
        """
        date_mapping: Dict[int, str] = {}
        fund_data: Dict[str, Dict[int, float]] = {code: {} for code in fund_codes}

        for code in fund_codes:
            logger.info(f"正在获取基金 {code} 的数据...")
            data = FundDataFetcher.get_fund_nav_data(code)

            if not data:
                logger.warning(f"基金 {code}: 数据获取失败，已跳过")
                continue

            for index, item in enumerate(reversed(data)):
                date_str = item.get('FSRQ', '')
                nav_value = item.get('DWJZ', '0')

                if index not in date_mapping:
                    date_mapping[index] = date_str

                try:
                    fund_data[code][index] = float(nav_value)
                except ValueError:
                    fund_data[code][index] = 0.0
                    logger.warning(f"基金 {code}: 第 {index} 天净值格式错误 - {nav_value}")

        return date_mapping, fund_data

    @classmethod
    def calculate_yaxis_range(cls, data_series: pd.Series, margin_ratio: float = 0.08) -> Tuple[float, float]:
        """
        计算Y轴的显示范围

        根据数据最大值和最小值，计算合适的Y轴显示范围，
        留出边距使图表视觉效果更好。

        Args:
            data_series: pandas Series，包含基金净值数据
            margin_ratio: 边距比例，默认8%（上下各留8%边距）

        Returns:
            Tuple[y_max, y_min]
            - y_max: Y轴最大值 = 数据最大值 × (1 + margin_ratio)
            - y_min: Y轴最小值 = 数据最小值 × (1 - margin_ratio)
            结果四舍五入保留4位小数

        示例:
            >>> calculate_yaxis_range(pd.Series([1.0, 1.1, 1.2]))
            (1.296, 0.92)
        """
        if data_series.empty:
            return 1.0, 0.0

        y_max = data_series.max() * (1 + margin_ratio)
        y_min = data_series.min() * (1 - margin_ratio)
        y_min = max(y_min, 0)

        return round(y_max, 4), round(y_min, 4)


class FundChartGenerator:
    """
    基金图表生成器

    负责将基金数据转换为交互式可视化图表。
    支持多基金对比、数据缩放、工具箱等功能。

    图表特性:
        - 交互式折线图，支持鼠标悬停查看详情
        - 数据缩放组件，支持滑块和内置缩放
        - 滚动图例，避免过多基金时重叠
        - 标记点和参考线（最大/最小值、平均值）
        - 工具箱（保存图片、数据视图、还原等）
    """

    FUND_CONFIG = {
        '沪深300': '510310',
        '中证500': '510500',
        '中证红利': '515180',
        '中证国防': '512670',
        '中证军工': '512660',
        '芯片': '159995',
        '机器人': '562500',
        '人工智能': '515980',
        '5G': '515050',
        '云计算': '516510',
        '恒生指数': '159920',
        '标普500': '513500'
    }

    ALTERNATIVE_FUND_CONFIG = {
        '沪深300': '007339',
        '中证500': '070039',
        '中证红利': '100032',
        '中证国防': '012041',
        '中证军工': '002199',
        '芯片': '008887',
        '机器人': '014881',
        '人工智能': '008082',
        '5G': '008086',
        '云计算': '017854',
        '恒生指数': '164705',
        '标普500': '050025'
    }

    def __init__(self, use_alternative: bool = True):
        """
        初始化图表生成器

        Args:
            use_alternative: 是否使用备选基金代码，默认True
                True: 使用 ALTERNATIVE_FUND_CONFIG
                False: 使用 FUND_CONFIG
        """
        self.fund_config = self.ALTERNATIVE_FUND_CONFIG if use_alternative else self.FUND_CONFIG
        self.fund_names = list(self.fund_config.keys())
        self.fund_codes = list(self.fund_config.values())

    def prepare_chart_data(self) -> Optional[pd.DataFrame]:
        """
        准备图表数据

        获取所有配置基金的净值数据，并转换为pandas DataFrame格式。

        Returns:
            DataFrame格式的基金数据，包含日期和各基金净值
            列: '日期', '基金名称1', '基金名称2', ...
            获取失败返回 None

        数据质量检查:
            - 检查数据是否为空
            - 检查数据条数
            - 统计包含的基金数量
        """
        logger.info("正在获取基金数据...")
        date_mapping, fund_data = FundDataProcessor.fetch_multiple_funds_data(self.fund_codes)

        if not date_mapping or not any(fund_data.values()):
            logger.error("无法获取有效的基金数据")
            return None

        nav_dict: Dict[str, Any] = {'日期': date_mapping}

        for name, code in self.fund_config.items():
            if code in fund_data and fund_data[code]:
                nav_dict[name] = fund_data[code]
            else:
                logger.warning(f"基金 {name}({code}): 数据为空，将用0填充")
                nav_dict[name] = {i: 0.0 for i in range(len(date_mapping))}

        nav_df = pd.DataFrame(nav_dict)

        logger.info(f"获取到 {len(nav_df)} 天的数据")
        logger.info(f"包含 {len(self.fund_names)} 个基金")

        return nav_df

    def generate_chart(self, nav_data: pd.DataFrame) -> Line:
        """
        生成基金净值走势图

        Args:
            nav_data: pandas DataFrame，包含日期和各基金净值数据

        Returns:
            pyecharts Line图表对象，可直接调用render()方法生成HTML

        图表配置:
            - 主题: LIGHT（浅色主题）
            - 尺寸: 1400x700像素
            - X轴: 日期，旋转45度避免重叠
            - Y轴: 单位净值，自动计算范围
            - 数据缩放: 内置型 + 滑块型
            - 图例: 滚动模式，支持多基金
        """
        logger.info("正在生成图表...")

        line_chart = Line(
            init_opts=opts.InitOpts(
                theme=ThemeType.LIGHT,
                width="1400px",
                height="800px",
                page_title="基金净值走势图",
                js_host=""
            )
        )

        dates = nav_data['日期'].tolist()
        line_chart.add_xaxis(dates)

        y_axis_ranges: List[Tuple[float, float]] = []

        for fund_name in self.fund_names:
            if fund_name not in nav_data.columns:
                continue

            fund_series_data = nav_data[fund_name].tolist()
            y_max, y_min = FundDataProcessor.calculate_yaxis_range(nav_data[fund_name])
            y_axis_ranges.append((y_max, y_min))

            line_chart.add_yaxis(
                series_name=fund_name,
                y_axis=fund_series_data,
                is_smooth=True,
                is_symbol_show=True,
                label_opts=opts.LabelOpts(is_show=False),
                markpoint_opts=opts.MarkPointOpts(
                    data=[
                        opts.MarkPointItem(type_="min", name="最低"),
                        opts.MarkPointItem(type_="max", name="最高")
                    ]
                ),
                markline_opts=opts.MarkLineOpts(
                    data=[opts.MarkLineItem(type_="average", name="均值")]
                )
            )

        all_y_max = max([r[0] for r in y_axis_ranges]) if y_axis_ranges else None
        all_y_min = min([r[1] for r in y_axis_ranges]) if y_axis_ranges else None

        line_chart.set_global_opts(
            tooltip_opts=opts.TooltipOpts(
                trigger="axis",
                axis_pointer_type="cross",
                background_color="rgba(255,255,255,0.9)"
            ),
            legend_opts=opts.LegendOpts(
                type_="scroll",
                pos_top="5%",
                pos_left="center"
            ),
            datazoom_opts=[
                opts.DataZoomOpts(range_start=0, range_end=100, type_="inside"),
                opts.DataZoomOpts(is_show=True, type_="slider", pos_bottom="5%")
            ],
            yaxis_opts=opts.AxisOpts(
                name="单位净值",
                name_location="end",
                max_=all_y_max,
                min_=all_y_min,
                axislabel_opts=opts.LabelOpts(formatter="{value}"),
                splitline_opts=opts.SplitLineOpts(is_show=True)
            ),
            xaxis_opts=opts.AxisOpts(
                name="日期",
                name_location="end",
                axislabel_opts=opts.LabelOpts(rotate=45),
                splitline_opts=opts.SplitLineOpts(is_show=True)
            ),
            toolbox_opts=opts.ToolboxOpts(
                is_show=True,
                feature={
                    "saveAsImage": {"title": "保存图片"},
                    "dataView": {"title": "数据视图", "lang": ["数据视图", "关闭", "刷新"]},
                    "restore": {"title": "还原"},
                    "dataZoom": {"title": "区域缩放"}
                }
            )
        )

        return line_chart

    def save_data_to_json(self, nav_data: pd.DataFrame, output_dir: str = ".") -> str:
        """
        将基金数据保存为JSON格式文件

        Args:
            nav_data: pandas DataFrame，包含日期和各基金净值数据
            output_dir: 输出目录路径，默认为当前目录

        Returns:
            保存的JSON文件完整路径

        输出文件:
            格式: JSON格式，包含日期和各基金净值数据
            文件名: fund_data.json
        """
        os.makedirs(output_dir, exist_ok=True)

        # 转换DataFrame为字典格式，便于JSON序列化
        data_dict = {
            'update_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'last_trading_date': nav_data['日期'].iloc[-1] if not nav_data.empty and '日期' in nav_data.columns else '未知',
            'total_days': len(nav_data),
            'fund_names': self.fund_names,
            'data': nav_data.to_dict('records')
        }

        output_path = os.path.join(output_dir, "fund_data.json")
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data_dict, f, ensure_ascii=False, indent=2)

        return output_path

    def save_chart_to_html(self, chart: Line, nav_data: pd.DataFrame, output_dir: str = ".") -> str:
        """
        将图表保存为HTML文件

        Args:
            chart: pyecharts Line图表对象
            nav_data: pandas DataFrame，包含日期和各基金净值数据
            output_dir: 输出目录路径，默认为当前目录

        Returns:
            保存的HTML文件完整路径

        输出文件:
            格式: 包含完整HTML、CSS、JavaScript的可独立运行网页
            文件名: index.html
        """
        os.makedirs(output_dir, exist_ok=True)

        output_path = os.path.join(output_dir, "index.html")
        chart.render(output_path)

        with open(output_path, 'r', encoding='utf-8') as f:
            html_content = f.read()

        dates = nav_data['日期'].tolist() if '日期' in nav_data.columns else []
        last_date = dates[-1] if dates else '未知'
        total_days = len(dates) if dates else 0

        title_div = f'''
        <div style="width:100%;text-align:center;padding:15px 0;margin:0;background:#f5f5f5;border-bottom:1px solid #ddd;">
            <h1 style="margin:0;font-size:22px;font-weight:bold;color:#333;font-family:Microsoft YaHei,sans-serif;">基金净值走势图</h1>
            <p style="margin:8px 0 0 0;font-size:13px;color:#666;font-family:Microsoft YaHei,sans-serif;">数据更新至: {last_date}  |  共 {total_days} 个交易日</p>
        </div>
'''

        import re
        chart_div_pattern = r'<div id="[a-f0-9]+" class="chart-container" style="width:\d+px; height:\d+px; "></div>'
        chart_div_match = re.search(chart_div_pattern, html_content)

        if chart_div_match:
            html_content = html_content.replace(
                chart_div_match.group(0),
                f'{title_div}\n        {chart_div_match.group(0)}'
            )

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        return output_path


def main() -> None:
    """
    主函数：执行基金数据获取、图表生成和保存的完整流程

    执行步骤:
        1. 输出程序开始运行信息
        2. 初始化图表生成器
        3. 获取并处理基金数据
        4. 生成交互式图表
        5. 保存为HTML文件
        6. 输出执行结果和数据摘要

    输出:
        - index.html: 交互式基金净值走势图网页
        - 控制台日志: 程序执行过程信息
    """
    print("=" * 50)
    print("基金净值走势可视化工具")
    print("=" * 50)

    try:
        logger.info("初始化图表生成器...")
        chart_generator = FundChartGenerator(use_alternative=True)

        nav_data = chart_generator.prepare_chart_data()

        if nav_data is None:
            logger.error("程序终止: 无法获取有效的基金数据")
            return

        chart = chart_generator.generate_chart(nav_data)

        # 保存数据为JSON文件
        json_path = chart_generator.save_data_to_json(nav_data)
        print(f"数据已保存至: {json_path}")

        output_path = chart_generator.save_chart_to_html(chart, nav_data)

        print("\n" + "=" * 50)
        print("程序执行完成！")
        print(f"图表已保存至: {output_path}")
        print(f"数据已保存至: {json_path}")
        print(f"请在浏览器中打开该文件查看图表")
        print("=" * 50)

        logger.info(f"数据摘要:")
        logger.info(f"时间范围: {nav_data['日期'].iloc[0]} 至 {nav_data['日期'].iloc[-1]}")
        logger.info(f"包含基金: {', '.join(chart_generator.fund_names)}")

    except Exception as e:
        logger.error(f"程序执行出错: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()