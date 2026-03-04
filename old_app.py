"""
基金净值走势图自动生成器

功能描述:
    本脚本从东方财富网基金数据中心抓取指定基金的历史净值数据，
    经过数据处理后生成交互式的净值走势图网页（HTML格式）。
    
主要特性:
    1. 支持多基金品种同时展示和对比
    2. 自动从网络获取最新净值数据
    3. 生成可交互的图表（支持缩放、悬停查看详情）
    4. 每日定时自动更新（配合GitHub Actions）
    5. 完善的错误处理和日志记录

使用方式:
    直接运行: python app.py
    生成的文件: index.html（项目根目录）

作者: Auto-generated
版本: 1.0
"""

import os
import re
import json
import logging
from typing import List, Dict, Any

import requests
import pandas as pd
from pyecharts import options as opts
from pyecharts.charts import Line
from pyecharts.globals import ThemeType

# =============================================================================
# 日志配置
# =============================================================================
# 配置日志格式和级别，INFO级别会输出所有INFO及以上级别的日志
# 格式: 时间 - 级别名称 - 消息内容
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
# 获取当前模块的日志记录器，用于在代码中输出日志
logger = logging.getLogger(__name__)

# =============================================================================
# 全局配置
# =============================================================================
# fund: 基金列表，每个基金包含name(显示名称)和code(基金代码)
#        基金代码为东方财富网使用的6位数字代码
# output_dir: 生成的HTML文件输出目录，"."表示当前根目录
# page_size: 每次请求获取的净值记录数量，默认20条
CONFIG = {
    "funds": [
        {"name": "中证500", "code": "160119"},
        {"name": "芯片", "code": "008887"},
        {"name": "5G", "code": "008086"},
        {"name": "云计算", "code": "017854"},
        {"name": "恒生指数", "code": "164705"},
        {"name": "人工智能", "code": "008082"},
    ],
    "output_dir": ".",
    "page_size": 20,
}


def jsjz_api(code: str, pageSize: int = 20) -> List[Dict[str, Any]]:
    """
    获取指定基金的净值历史数据
    
    参数说明:
        code: 基金代码，6位数字字符串，如'160119'
        pageSize: 每次请求返回的记录数量，默认20条
    
    返回值:
        成功返回净值记录列表，每条记录包含日期(FSRQ)、单位净值(DWJZ)等字段
        失败返回空列表
    
    数据来源:
        东方财富网基金历史净值接口: http://api.fund.eastmoney.com/f10/lsjz
    
    接口特点:
        返回JSONP格式数据（被JavaScript函数调用的JSON）
        需要正确的Referer和User-Agent请求头才能访问
        返回数据按日期倒序排列（最新在前）
    """
    # 构建完整的请求URL，将各参数拼接
    # callback: JSONP回调函数名，用于包裹返回的JSON数据
    # fundCode: 基金代码
    # pageIndex/pageSize: 分页参数
    # startDate/endDate: 日期范围筛选，默认为空获取所有数据
    url = (
        f"http://api.fund.eastmoney.com/f10/lsjz"
        f"?callback=jQuery1830041192874394646584_1617938643457"
        f"&fundCode={code}"
        f"&pageIndex=1"
        f"&pageSize={pageSize}"
        f"&startDate=&endDate=&_=1617939181252"
    )
    
    # 请求头配置，模拟浏览器访问
    # Referer: 设置为基金详情页URL，表示从基金页面跳转而来
    # User-Agent: 浏览器标识，避免被服务器识别为爬虫
    headers = {
        "Referer": "http://fundf10.eastmoney.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    
    try:
        # 发送HTTP GET请求
        # timeout=30: 设置30秒超时，防止请求无限期挂起
        resp = requests.get(url, headers=headers, timeout=30)
        
        # 检查HTTP响应状态码，4xx/5xx会抛出异常
        resp.raise_for_status()
        
        # 获取响应体文本内容
        # 返回格式类似: jQuery1830041192874394646584_1617938643457({"Data": {...}})
        html = resp.text
        
        # 使用正则表达式提取括号内的JSON数据
        # 正则解释: \( 匹配左括号，(.*?) 非贪婪匹配任意字符直到下一个模式，\) 匹配右括号
        res = re.findall(r"\((.*?)\)", html)
        
        # 如果没有匹配到数据，返回空列表
        if not res:
            logger.warning(f"基金 {code} 返回数据为空")
            return []
        
        # 解析JSON字符串为Python字典
        # res[0] 是提取出来的JSON字符串
        data = json.loads(res[0])
        
        # 从返回数据中提取净值列表
        # 格式: {"Data": {"LSJZList": [...]}}
        # 使用get方法避免KeyError，如果没有数据返回空列表
        return data.get("Data", {}).get("LSJZList", [])
    
    # 捕获网络请求相关异常
    except requests.RequestException as e:
        logger.error(f"请求失败 (基金 {code}): {e}")
        return []
    
    # 捕获JSON解析异常
    except json.JSONDecodeError as e:
        logger.error(f"JSON 解析失败 (基金 {code}): {e}")
        return []
    
    # 捕获其他未知异常，确保程序不会崩溃
    except Exception as e:
        logger.error(f"未知错误 (基金 {code}): {e}")
        return []


def fetch_fund_data(codes: List[str]) -> tuple:
    """
    批量获取多个基金的净值数据
    
    参数说明:
        codes: 基金代码列表，如 ['160119', '008887']
    
    返回值:
        元组 (riqi, fund_data)
        - riqi: 字典，{索引: 日期字符串}
        - fund_data: 字典，{基金代码: {索引: 净值数值}}
        两个字典使用相同索引对齐数据
    
    数据对齐说明:
        由于不同基金交易日可能不同（节假日休市），
        采用反向遍历方式，从最新数据开始填充，
        确保所有基金共享相同的日期索引
    """
    # riqi字典: 存储索引到日期的映射
    # 例如: {0: '2025-01-10', 1: '2025-01-09', ...}
    riqi = {}
    
    # fund_data字典: 存储每个基金的净值数据
    # 初始化为 {基金代码: {}}
    fund_data = {code: {} for code in codes}
    
    # 遍历每个基金代码获取数据
    for code in codes:
        # 调用接口获取该基金的净值列表
        data = jsjz_api(code)
        
        # 反向遍历数据，从最新日期开始
        # reversed() 将列表反转，最新数据在前
        for index, item in enumerate(reversed(data)):
            # item['FSRQ'] 是净值日期，格式: YYYY-MM-DD
            riqi[index] = item["FSRQ"]
            # item['DWJZ'] 是单位净值，转换为浮点数
            fund_data[code][index] = float(item["DWJZ"])
    
    return riqi, fund_data


def set_y_axis(data) -> tuple:
    """
    根据数据计算Y轴的显示范围
    
    参数说明:
        data: pandas Series类型，包含基金的净值数据
    
    返回值:
        元组 (y_max, y_min)
        - y_max: Y轴最大值 = 数据最大值 × 1.08
        - y_min: Y轴最小值 = 数据最小值 × 0.92
    
    计算说明:
        乘以系数是为了在数据点和坐标轴之间留出边距
        1.08和0.92是经验值，使图表视觉效果更好
        结果保留4位小数
    """
    # 计算Y轴范围，并四舍五入保留4位小数
    y_max = round(data.max() * 1.08, 4)
    y_min = round(data.min() * 0.92, 4)
    
    return y_max, y_min


def generate_chart() -> Line:
    """
    生成基金净值走势图图表
    
    处理流程:
        1. 从CONFIG获取基金配置信息
        2. 批量获取所有基金的净值数据
        3. 将数据转换为pandas DataFrame格式
        4. 创建折线图并绑定数据
        5. 添加最大/最小值标记和平均值参考线
        6. 配置图表全局选项
    
    返回值:
        Line对象: 配置完成的pyecharts折线图对象
    
    图表特性:
        - 交互式: 支持缩放、悬停查看详情、点击图例切换显示
        - 多系列: 每个基金一条折线
        - 标记点: 自动标注最大/最小值
        - 参考线: 显示平均值
    """
    # 从CONFIG中提取基金名称和代码列表
    # names: ['中证500', '芯片', ...]
    # codes: ['160119', '008887', ...]
    names = [f["name"] for f in CONFIG["funds"]]
    codes = [f["code"] for f in CONFIG["funds"]]
    
    # 获取所有基金的净值数据
    riqi, cn_data = fetch_fund_data(codes)
    
    # 构建DataFrame数据
    # nav_dict格式: {'日期': {0: '2025-01-10', ...}, '160119': {...}, '008887': {...}}
    nav_dict = {"日期": riqi}
    for code, data in cn_data.items():
        nav_dict[code] = data
    
    # 转换为pandas DataFrame，便于数据处理
    # 每列代表一个基金，索引为日期序列
    nav_data = pd.DataFrame(nav_dict)
    
    # 创建折线图对象
    # InitOpts: 初始化配置
    # theme=ThemeType.LIGHT: 使用浅色主题
    # width/height: 图表尺寸（像素）
    line = Line(
        init_opts=opts.InitOpts(
            theme=ThemeType.LIGHT,
            width="1200px",
            height="500px"
        )
    )
    
    # 设置X轴数据
    # 将日期列表转换为Python列表
    line.add_xaxis(nav_data["日期"].tolist())
    
    # 用于存储每个基金的Y轴范围配置
    fund_series = []
    
    # 遍历每个基金，添加一条折线
    for name, code in zip(names, codes):
        # 获取该基金的净值数据列表
        y_data = nav_data[code].tolist()
        
        # 计算该基金的Y轴范围
        y_max, y_min = set_y_axis(nav_data[code])
        
        # 保存配置信息
        fund_series.append(
            {
                "name": name,
                "y_data": y_data,
                "y_max": y_max,
                "y_min": y_min,
            }
        )
        
        # 添加Y轴数据系列
        # series_name: 图例名称
        # y_axis: Y轴数据列表
        # is_symbol_show: 是否显示数据点标记
        line.add_yaxis(
            series_name=name,
            y_axis=y_data,
            is_symbol_show=True,
            
            # 标记点配置：标注最大值和最小值
            markpoint_opts=opts.MarkPointOpts(
                data=[
                    opts.MarkPointItem(type_="min", name="最小值"),
                    opts.MarkPointItem(type_="max", name="最大值"),
                ]
            ),
            
            # 标记线配置：显示平均值参考线
            markline_opts=opts.MarkLineOpts(
                data=[opts.MarkLineItem(type_="average", name="平均值")]
            ),
        )
    
    # 设置全局配置
    line.set_global_opts(
        # 标题配置
        title_opts=opts.TitleOpts(
            title="净值走势图",
            subtitle="数据来源: 东方财富"
        ),
        
        # 缩放组件配置：添加X轴缩放滑块
        datazoom_opts=[opts.DataZoomOpts()],
        
        # Y轴配置
        yaxis_opts=opts.AxisOpts(
            # Y轴最大值：所有基金的最大值中的最大值
            max_=max(fund["y_max"] for fund in fund_series),
            # Y轴最小值：所有基金的最小值中的最小值
            min_=min(fund["y_min"] for fund in fund_series),
            # 刻度间隔
            interval=0.02,
        ),
    )
    
    return line


def main() -> None:
    """
    主函数：执行完整的图表生成流程
    
    执行步骤:
        1. 输出开始运行日志
        2. 检查并创建输出目录
        3. 调用generate_chart()生成图表
        4. 将图表渲染为HTML文件
        5. 验证文件是否创建成功
    
    输出文件:
        位置: CONFIG["output_dir"] 指定的目录
        文件名: index.html
        格式: 包含完整HTML、CSS、JavaScript的可独立运行的网页
    """
    # 输出开始运行日志
    logger.info("开始生成基金净值走势图...")
    
    # 获取输出目录路径
    output_dir = CONFIG["output_dir"]
    
    # 检查输出目录是否存在
    if not os.path.exists(output_dir):
        # 不存在则创建目录（包括多级目录）
        os.makedirs(output_dir)
        logger.info(f"已创建目录: {output_dir}")
    
    # 生成图表对象
    chart = generate_chart()
    
    # 构建输出文件完整路径
    output_path = os.path.join(output_dir, "index.html")
    
    # 将图表渲染为HTML文件
    # render() 方法会生成包含所有图表代码的HTML文件
    chart.render(output_path)
    logger.info(f"网站已成功生成在 {output_path}")
    
    # 验证文件是否创建成功
    if os.path.exists(output_path):
        logger.info("✅ 文件创建成功！")
    else:
        logger.error("❌ 文件创建失败，请检查权限或路径")


# =============================================================================
# 程序入口
# =============================================================================
# 当脚本直接运行时（而不是被导入为模块时），执行main函数
# 这是Python的常用模式
if __name__ == "__main__":
    main()
