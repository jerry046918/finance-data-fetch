import akshare as ak
import pandas as pd
import sqlite3
import time
import argparse
import json
import os
from datetime import datetime, timedelta
from typing import List, Dict
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class FundDataCollector:
    def __init__(self, db_path: str = "data/funds.db"):
        self.db_path = db_path
        self.conn = None
        self.cursor = None
        self.init_database()
        
    def init_database(self):
        """初始化SQLite数据库结构"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        
        # 基金基础信息表（含最新净值）
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS funds_meta (
                fund_code TEXT PRIMARY KEY,
                fund_name TEXT,
                fund_type TEXT,
                latest_nav REAL,
                nav_date TEXT,
                update_time TEXT,
                quarter TEXT  -- 最新持仓报告期，如"2024Q3"
            )
        ''')
        
        # 持仓明细表（复合主键：基金代码+股票代码+季度）
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS holdings (
                fund_code TEXT,
                stock_code TEXT,
                stock_name TEXT,
                hold_ratio REAL,  -- 占净值比(%)
                hold_value REAL,  -- 持仓市值(万元)
                quarter TEXT,     -- 报告期
                PRIMARY KEY (fund_code, stock_code, quarter)
            )
        ''')
        
        # 创建索引加速查询
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_holdings_code ON holdings(fund_code)')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_holdings_stock ON holdings(stock_code)')
        self.conn.commit()
        
    def get_fund_list(self, fund_type: str = "all") -> pd.DataFrame:
        """
        获取基金列表，过滤主要类型
        fund_type: all/equity(股票型)/mix(混合型)/index(指数型)
        """
        logger.info("正在获取基金列表...")
        df = ak.fund_name_em()
        
        # 列名标准化（akshare不同版本可能有差异）
        df.columns = [col.strip() for col in df.columns]
        
        # 过滤主要类型（排除货币基金、债券基金等）
        if fund_type != "all":
            type_mapping = {
                "equity": ["股票型", "股票"],
                "mix": ["混合型", "混合"],
                "index": ["指数型", "指数", "ETF", "QDII"]
            }
            keywords = type_mapping.get(fund_type, [])
            mask = df['基金类型'].str.contains('|'.join(keywords), na=False)
            df = df[mask]
        
        # 排除货币基金（通常无持仓分析价值且数量庞大）
        df = df[~df['基金类型'].str.contains('货币|债券', na=False)]
        
        logger.info(f"筛选后基金数量: {len(df)}")
        return df
    
    def get_latest_quarter(self) -> str:
        """自动计算当前应获取的最新报告期"""
        now = datetime.now()
        year = now.year
        month = now.month
        
        # 报告期规则：Q1(1-3月，4月披露), Q2/H1(4-6月，7-8月披露), Q3(7-9月，10月披露), Q4/Annual(10-12月，次年3-4月披露)
        if month >= 10:
            quarter = f"{year}Q3"
        elif month >= 7:
            quarter = f"{year}Q2" if month == 7 else f"{year}Q3"  # 8-9月Q2已披露完
        elif month >= 4:
            quarter = f"{year}Q1"
        else:
            quarter = f"{year-1}Q4"  # 年初获取上年报
            
        return quarter
    
    def fetch_nav_data(self, fund_codes: List[str]) -> Dict[str, dict]:
        """
        批量获取基金净值（使用open_fund_daily接口获取最新净值）
        注意：此接口返回全市场数据，需要过滤
        """
        logger.info("正在获取最新净值数据...")
        try:
            # 获取今日或昨日净值（取决于当前时间）
            nav_df = ak.fund_open_fund_daily_em()
            nav_df = nav_df[nav_df['基金代码'].isin(fund_codes)]
            
            # 找到包含"单位净值"的列名（格式为"日期-单位净值"）
            nav_cols = [col for col in nav_df.columns if '单位净值' in col and '-' in col]
            date_col = nav_cols[0] if nav_cols else None
            
            nav_map = {}
            for _, row in nav_df.iterrows():
                nav_value = row[date_col] if date_col and pd.notna(row.get(date_col)) else None
                nav_map[row['基金代码']] = {
                    'nav': float(nav_value) if nav_value is not None else None,
                    'date': date_col.split('-单位净值')[0] if date_col else None  # 提取日期部分
                }
            return nav_map
        except Exception as e:
            logger.error(f"获取净值数据失败: {e}")
            return {}
    
    def fetch_single_fund_holdings(self, fund_code: str, quarter: str, max_retry: int = 3) -> pd.DataFrame:
        """获取单只基金持仓，带重试机制"""
        for attempt in range(max_retry):
            try:
                # akshare的持仓接口，date参数通常是年份，但实际返回最新季度
                # 注意：不同akshare版本参数可能有差异，这里使用通用方式
                df = ak.fund_portfolio_hold_em(symbol=fund_code, date=quarter[:4])
                
                if df is not None and not df.empty:
                    # 标准化列名
                    df = df.rename(columns={
                        '股票代码': 'stock_code',
                        '股票名称': 'stock_name',
                        '占净值比例': 'hold_ratio',
                        '持仓市值': 'hold_value',
                        '季度': 'quarter_detail'
                    })
                    
                    # 确保数值类型正确
                    df['hold_ratio'] = pd.to_numeric(df['hold_ratio'], errors='coerce')
                    df['hold_value'] = pd.to_numeric(df['hold_value'], errors='coerce')
                    
                    # 添加基金代码和季度
                    df['fund_code'] = fund_code
                    df['quarter'] = quarter
                    
                    # 选择需要的列
                    return df[['fund_code', 'stock_code', 'stock_name', 'hold_ratio', 'hold_value', 'quarter']]
                    
            except Exception as e:
                logger.warning(f"获取 {fund_code} 持仓失败 (尝试 {attempt+1}/{max_retry}): {e}")
                if attempt < max_retry - 1:
                    time.sleep(2 ** attempt)  # 指数退避
                else:
                    return pd.DataFrame()
        
        return pd.DataFrame()
    
    def process_batch(self, fund_batch: pd.DataFrame, quarter: str, delay: float):
        """处理一批基金"""
        batch_holdings = []
        batch_meta = []
        
        # 先获取这批基金的净值（批量接口更高效）
        nav_data = self.fetch_nav_data(fund_batch['基金代码'].tolist())
        
        for idx, row in fund_batch.iterrows():
            code = row['基金代码']
            name = row['基金简称']
            f_type = row.get('基金类型', '未知')
            
            logger.info(f"处理 [{code}] {name} ({idx+1}/{len(fund_batch)})")
            
            # 获取持仓
            holdings = self.fetch_single_fund_holdings(code, quarter)
            if not holdings.empty:
                batch_holdings.append(holdings)
            
            # 组装元数据
            nav_info = nav_data.get(code, {})
            batch_meta.append({
                'fund_code': code,
                'fund_name': name,
                'fund_type': f_type,
                'latest_nav': nav_info.get('nav'),
                'nav_date': nav_info.get('date'),
                'update_time': datetime.now().isoformat(),
                'quarter': quarter if not holdings.empty else None
            })
            
            time.sleep(delay)  # 限速，避免被封
        
        return batch_holdings, batch_meta
    
    def save_to_database(self, holdings_list: List[pd.DataFrame], meta_list: List[dict]):
        """保存到SQLite"""
        if not holdings_list:
            logger.warning("没有持仓数据需要保存")
            return
            
        # 合并持仓数据
        all_holdings = pd.concat(holdings_list, ignore_index=True)
        all_holdings.to_sql('holdings', self.conn, if_exists='replace', index=False)
        
        # 更新元数据（使用UPSERT逻辑）
        meta_df = pd.DataFrame(meta_list)
        meta_df.to_sql('funds_meta_temp', self.conn, if_exists='replace', index=False)
        
        # 合并更新（保留历史记录中的有效数据）
        self.cursor.execute('''
            INSERT OR REPLACE INTO funds_meta 
            SELECT * FROM funds_meta_temp
        ''')
        self.cursor.execute('DROP TABLE IF EXISTS funds_meta_temp')
        
        self.conn.commit()
        logger.info(f"数据库已更新: {len(meta_list)} 只基金, {len(all_holdings)} 条持仓记录")
    
    def generate_summary(self):
        """生成统计摘要"""
        stats = {}
        
        # 基金数量
        self.cursor.execute("SELECT COUNT(*) FROM funds_meta")
        stats['total_funds'] = self.cursor.fetchone()[0]
        
        # 持仓记录数
        self.cursor.execute("SELECT COUNT(*) FROM holdings")
        stats['total_holdings'] = self.cursor.fetchone()[0]
        
        # 覆盖的股票数
        self.cursor.execute("SELECT COUNT(DISTINCT stock_code) FROM holdings")
        stats['unique_stocks'] = self.cursor.fetchone()[0]
        
        # 最新报告期
        self.cursor.execute("SELECT DISTINCT quarter FROM holdings LIMIT 1")
        result = self.cursor.fetchone()
        stats['quarter'] = result[0] if result else 'N/A'
        
        # 保存摘要到JSON（方便App快速读取元数据）
        with open('data/meta.json', 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
        
        return stats
    
    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()

def main():
    parser = argparse.ArgumentParser(description='抓取公募基金数据')
    parser.add_argument('--type', default='all', help='基金类型: all/equity/mix/index')
    parser.add_argument('--batch-size', type=int, default=50, help='每批处理的基金数量')
    parser.add_argument('--delay', type=float, default=1.5, help='请求间隔(秒)')
    parser.add_argument('--limit', type=int, default=None, help='限制处理数量（用于测试）')
    args = parser.parse_args()
    
    collector = FundDataCollector()
    
    try:
        # 1. 获取基金列表
        fund_df = collector.get_fund_list(args.type)
        if args.limit:
            fund_df = fund_df.head(args.limit)
        
        total = len(fund_df)
        logger.info(f"计划处理 {total} 只基金")
        
        # 2. 确定报告期
        quarter = collector.get_latest_quarter()
        logger.info(f"目标报告期: {quarter}")
        
        # 3. 分批处理
        all_holdings = []
        all_meta = []
        
        for start_idx in range(0, total, args.batch_size):
            end_idx = min(start_idx + args.batch_size, total)
            batch = fund_df.iloc[start_idx:end_idx]
            
            logger.info(f"处理批次 {start_idx//args.batch_size + 1}/{(total-1)//args.batch_size + 1} ({start_idx+1}-{end_idx})")
            
            holdings, meta = collector.process_batch(batch, quarter, args.delay)
            all_holdings.extend(holdings)
            all_meta.extend(meta)
            
            # 每完成一批，短暂休息
            if end_idx < total:
                time.sleep(5)
        
        # 4. 保存到数据库
        collector.save_to_database(all_holdings, all_meta)
        
        # 5. 生成统计
        stats = collector.generate_summary()
        logger.info(f"完成! 统计: {stats}")
        
    except Exception as e:
        logger.error(f"程序异常: {e}", exc_info=True)
        raise
    finally:
        collector.close()

if __name__ == "__main__":
    main()