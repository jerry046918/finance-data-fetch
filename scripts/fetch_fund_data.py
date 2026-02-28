#!/usr/bin/env python3
"""
公募基金基础数据采集工具（简化版）

只获取基金列表和净值数据，通过基金类型映射资产大类。
用于资产配置分析，不需要持仓明细。
"""

import akshare as ak
import pandas as pd
import sqlite3
import time
import argparse
import json
import os
from datetime import datetime
from typing import Dict, List, Optional
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================
# 基金类型 -> 资产大类映射
# ============================================================

FUND_TYPE_TO_ASSET_CLASS = {
    # 股票类
    '股票型': '股票',
    '混合型-偏股': '股票',
    '混合型-平衡': '股票',
    '混合型-灵活': '股票',  # 灵活配置，默认归为股票
    '指数型-股票': '股票',
    '指数型-海外股票': '海外股票',
    
    # 债券类
    '债券型-长债': '债券',
    '债券型-中短债': '债券',
    '债券型-混合一级': '债券',
    '债券型-混合二级': '债券',
    '混合型-偏债': '债券',
    '指数型-固收': '债券',
    
    # 现金/货币
    '货币型-普通货币': '现金',
    '货币型-浮动净值': '现金',
    
    # FOF（根据风险等级归类）
    'FOF-进取型': '股票',
    'FOF-均衡型': '混合',
    'FOF-稳健型': '债券',
    
    # QDII 股票
    'QDII-普通股票': '海外股票',
    'QDII-混合偏股': '海外股票',
    'QDII-混合灵活': '海外股票',
    'QDII-混合平衡': '海外股票',
    
    # QDII 债券
    'QDII-纯债': '海外债券',
    'QDII-混合债': '海外债券',
    
    # QDII 其他
    'QDII-商品': '商品',
    'QDII-REITs': '不动产',
    'QDII-FOF': '海外混合',
    
    # 另类投资
    'Reits': '不动产',
    'REITs': '不动产',
    '商品': '商品',
    
    # 其他
    '混合型-绝对收益': '混合',
    '指数型-其他': '混合',
}

# 未匹配类型的默认值
DEFAULT_ASSET_CLASS = '其他'


def map_fund_type_to_asset_class(fund_type: str) -> str:
    """
    将基金类型映射到资产大类
    
    Args:
        fund_type: 基金类型，如 '混合型-偏股'
    
    Returns:
        资产大类，如 '股票'
    """
    # 精确匹配
    if fund_type in FUND_TYPE_TO_ASSET_CLASS:
        return FUND_TYPE_TO_ASSET_CLASS[fund_type]
    
    # 模糊匹配（处理可能的新类型）
    for pattern, asset_class in FUND_TYPE_TO_ASSET_CLASS.items():
        if pattern in fund_type or fund_type in pattern:
            return asset_class
    
    # 关键词匹配
    if '股票' in fund_type or '权益' in fund_type:
        return '股票'
    if '债券' in fund_type or '债' in fund_type:
        return '债券'
    if '货币' in fund_type or '现金' in fund_type:
        return '现金'
    if 'QDII' in fund_type:
        return '海外混合'
    if 'FOF' in fund_type:
        return '混合'
    if 'REIT' in fund_type.lower() or 'reit' in fund_type.lower():
        return '不动产'
    if '商品' in fund_type:
        return '商品'
    
    return DEFAULT_ASSET_CLASS


class FundDataCollector:
    """基金数据采集器（简化版）"""
    
    def __init__(self, db_path: str = "data/funds.db"):
        self.db_path = db_path
        self.conn = None
        self.cursor = None
        self.init_database()
        
    def init_database(self):
        """初始化数据库"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        
        # 基金基础信息表
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS funds (
                fund_code TEXT PRIMARY KEY,
                fund_name TEXT,
                fund_type TEXT,
                asset_class TEXT,
                latest_nav REAL,
                nav_date TEXT,
                update_time TEXT
            )
        ''')
        
        # 创建索引
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_asset_class ON funds(asset_class)')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_fund_type ON funds(fund_type)')
        
        self.conn.commit()
        
    def get_fund_list(self) -> pd.DataFrame:
        """获取全部基金列表"""
        logger.info("正在获取基金列表...")
        df = ak.fund_name_em()
        
        # 标准化列名
        df.columns = [col.strip() for col in df.columns]
        
        logger.info(f"获取到 {len(df)} 只基金")
        return df
    
    def fetch_nav_data(self, fund_codes: List[str]) -> Dict[str, dict]:
        """
        批量获取基金净值
        
        Args:
            fund_codes: 基金代码列表
        
        Returns:
            {基金代码: {'nav': 净值, 'date': 日期}}
        """
        logger.info("正在获取净值数据...")
        
        try:
            nav_df = ak.fund_open_fund_daily_em()
            nav_df = nav_df[nav_df['基金代码'].isin(fund_codes)]
            
            # 找到包含"单位净值"的列名（格式为"日期-单位净值"）
            nav_cols = [col for col in nav_df.columns if '单位净值' in col and '-' in col]
            date_col = nav_cols[0] if nav_cols else None
            
            nav_map = {}
            for _, row in nav_df.iterrows():
                raw_value = row.get(date_col) if date_col else None
                # 检查非空、非NaN、非空字符串
                nav_value = raw_value if raw_value is not None and pd.notna(raw_value) and str(raw_value).strip() != '' else None
                nav_map[row['基金代码']] = {
                    'nav': float(nav_value) if nav_value is not None else None,
                    'date': date_col.split('-单位净值')[0] if date_col else None
                }
            
            logger.info(f"获取到 {len(nav_map)} 只基金的净值数据")
            return nav_map
            
        except Exception as e:
            logger.error(f"获取净值数据失败: {e}")
            return {}
    
    def process_funds(self, limit: Optional[int] = None) -> pd.DataFrame:
        """
        处理所有基金数据
        
        Args:
            limit: 限制处理数量（用于测试）
        
        Returns:
            处理后的 DataFrame
        """
        # 1. 获取基金列表
        fund_df = self.get_fund_list()
        
        if limit:
            fund_df = fund_df.head(limit)
            logger.info(f"限制处理前 {limit} 只基金")
        
        # 2. 获取净值数据
        fund_codes = fund_df['基金代码'].tolist()
        nav_data = self.fetch_nav_data(fund_codes)
        
        # 3. 组装数据
        records = []
        for _, row in fund_df.iterrows():
            code = row['基金代码']
            fund_type = row.get('基金类型', '')
            nav_info = nav_data.get(code, {})
            
            records.append({
                'fund_code': code,
                'fund_name': row.get('基金简称', ''),
                'fund_type': fund_type,
                'asset_class': map_fund_type_to_asset_class(fund_type),
                'latest_nav': nav_info.get('nav'),
                'nav_date': nav_info.get('date'),
                'update_time': datetime.now().isoformat()
            })
        
        return pd.DataFrame(records)
    
    def save_to_database(self, df: pd.DataFrame):
        """保存到数据库"""
        if df.empty:
            logger.warning("没有数据需要保存")
            return
        
        # 使用 replace 模式（每次全量更新）
        df.to_sql('funds', self.conn, if_exists='replace', index=False)
        self.conn.commit()
        
        logger.info(f"已保存 {len(df)} 条记录到数据库")
    
    def generate_summary(self) -> dict:
        """生成统计摘要"""
        stats = {}
        
        # 总基金数
        self.cursor.execute("SELECT COUNT(*) FROM funds")
        stats['total_funds'] = self.cursor.fetchone()[0]
        
        # 按资产大类统计
        self.cursor.execute('''
            SELECT asset_class, COUNT(*) as count 
            FROM funds 
            GROUP BY asset_class 
            ORDER BY count DESC
        ''')
        stats['by_asset_class'] = dict(self.cursor.fetchall())
        
        # 按基金类型统计
        self.cursor.execute('''
            SELECT fund_type, COUNT(*) as count 
            FROM funds 
            GROUP BY fund_type 
            ORDER BY count DESC
            LIMIT 20
        ''')
        stats['by_fund_type'] = dict(self.cursor.fetchall())
        
        # 更新时间
        self.cursor.execute("SELECT MAX(update_time) FROM funds")
        stats['update_time'] = self.cursor.fetchone()[0]
        
        # 保存摘要
        os.makedirs('data', exist_ok=True)
        with open('data/summary.json', 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
        
        return stats
    
    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()


def main():
    parser = argparse.ArgumentParser(description='抓取公募基金基础数据（简化版）')
    parser.add_argument('--limit', type=int, default=None, help='限制处理数量（用于测试）')
    parser.add_argument('--db', default='data/funds.db', help='数据库路径')
    args = parser.parse_args()
    
    collector = FundDataCollector(db_path=args.db)
    
    try:
        # 处理数据
        df = collector.process_funds(limit=args.limit)
        
        # 保存
        collector.save_to_database(df)
        
        # 生成统计
        stats = collector.generate_summary()
        logger.info(f"完成! 统计: {stats}")
        
    except Exception as e:
        logger.error(f"程序异常: {e}", exc_info=True)
        raise
    finally:
        collector.close()


if __name__ == "__main__":
    main()
